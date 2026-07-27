"""営業訪問者 管理システム（Streamlit）。

メイン画面は「業界一覧 → 会社一覧 → 営業記録 → 詳細」のドリルダウン。
「営業記録の作成」で資料（PDF/画像/名刺）をアップロードすると、Claude API で
会社名・担当者・事業概要・営業内容などを自動抽出してフォームに反映。
業界・営業日は利用者が選択する。会社の事業概要はHP検索でも取得できる。
"""
import io
import os
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import database
from config import STATUSES, INDUSTRIES, INBOX_DIR, SUPPORTED_EXTS
import importer
import storage
import extractor

st.set_page_config(page_title="営業訪問者 管理", page_icon="🧑‍💼", layout="wide")


def _disable_browser_translation():
    """ブラウザの自動翻訳による React の removeChild エラーを防ぐ。

    日本語ページを Chrome/Edge が翻訳するとDOMノードが差し替わり、
    Streamlit(React) の再描画と衝突して NotFound: removeChild が出る。
    親ドキュメントに translate=no / notranslate を設定して翻訳を抑止する。
    """
    components.html(
        """
        <script>
        try {
          const doc = window.parent.document;
          doc.documentElement.setAttribute('translate', 'no');
          doc.documentElement.lang = 'ja';
          doc.documentElement.classList.add('notranslate');
          if (!doc.querySelector('meta[name="google"][content="notranslate"]')) {
            const m = doc.createElement('meta');
            m.name = 'google'; m.content = 'notranslate';
            doc.head.appendChild(m);
          }
        } catch (e) {}
        </script>
        """,
        height=0,
    )


_disable_browser_translation()
database.init_db()

STATUS_FILTER = ["すべて"] + STATUSES
NO_COMPANY = "（会社名なし）"


def _has_api_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# フリーメール（ドメインからHPを推定しない）
_FREE_MAIL = {
    "gmail.com", "yahoo.co.jp", "yahoo.com", "outlook.com", "outlook.jp", "hotmail.com",
    "hotmail.co.jp", "icloud.com", "docomo.ne.jp", "ezweb.ne.jp", "au.com", "softbank.ne.jp",
    "me.com", "live.jp", "aol.com",
}


def _company_website(rows):
    """会社の公式HP URL を推定する。website列 → メールドメインの順。無ければ None。"""
    for r in rows:
        w = (r.get("website") or "").strip()
        if w:
            return w if w.startswith(("http://", "https://")) else "https://" + w
    for r in rows:
        e = (r.get("email") or "").strip()
        if "@" in e:
            dom = e.split("@", 1)[1].strip().lower().rstrip(".")
            if dom and dom not in _FREE_MAIL and "." in dom:
                return "https://" + dom
    return None


def _goto(**kw):
    """ナビゲーション状態を更新して再描画。"""
    for k, v in kw.items():
        st.session_state[k] = v
    st.rerun()


# ============================================================ 業界から探す
def page_browse():
    industry = st.session_state.get("sel_industry")
    company = st.session_state.get("sel_company")
    record = st.session_state.get("sel_record")

    if industry is None:
        _view_industries()
    elif company is None:
        _view_companies(industry)
    elif record is None:
        _view_company_records(industry, company)
    else:
        _view_record_detail(industry, company, record)


def _view_industries():
    st.header("🏭 業界から探す")
    st.caption("業界を選ぶと、その業界の会社一覧が表示されます。")
    counts = database.get_industry_counts()
    if not counts:
        st.info("データがありません。『営業記録の作成』から登録してください。")
        return

    cols = st.columns(3)
    for i, row in enumerate(counts):
        with cols[i % 3]:
            label = f"**{row['industry']}**\n\n🏢 {row['companies']}社 ／ 📄 {row['records']}件"
            if st.button(label, key=f"ind_{row['industry']}", use_container_width=True):
                _goto(sel_industry=row["industry"], sel_company=None, sel_record=None)


def _view_companies(industry):
    c1, c2 = st.columns([1, 5])
    if c1.button("← 業界一覧へ", use_container_width=True):
        _goto(sel_industry=None, sel_company=None, sel_record=None)
    c2.header(f"🏢 {industry} の会社")

    companies = database.get_companies_in_industry(industry)
    if not companies:
        st.info("この業界の会社がありません。")
        return

    st.caption("会社名（左）をタップすると営業記録に進みます。右は事業概要です。")
    h1, h2 = st.columns([2, 4])
    h1.markdown("**会社名**")
    h2.markdown("**事業概要**")
    for row in companies:
        name = row["company_name"] or NO_COMPANY
        col_name, col_ov = st.columns([2, 4], vertical_alignment="center")
        with col_name:
            if st.button(f"🏢 {name}\n\n📄 {row['records']}件",
                         key=f"co_{row['company_name']}", use_container_width=True):
                _goto(sel_company=row["company_name"], sel_record=None)
        col_ov.write(row.get("business_overview") or "（事業概要なし）")
        st.divider()


def _view_company_records(industry, company):
    rows = database.get_visits(industry=industry, company=company)
    url = _company_website(rows)

    c1, c2, c3 = st.columns([1.2, 3.4, 1.4], vertical_alignment="center")
    if c1.button("← 会社一覧へ", use_container_width=True):
        _goto(sel_company=None, sel_record=None)
    c2.header(f"📄 {company or NO_COMPANY}")
    if url:
        c3.link_button("🌐 公式HP", url, use_container_width=True)
    elif company:
        c3.link_button("🌐 HPを検索", f"https://www.google.com/search?q={quote(company + ' 公式サイト')}",
                       use_container_width=True)
    st.caption(f"業界: {industry}")

    if not rows:
        st.info("記録がありません。")
        return

    st.caption("担当者名の枠をタップすると詳細画面へ移動します。")
    for v in rows:
        rep = v["rep_name"] or "（担当者不明）"
        content = v["sales_content"] or "（営業内容なし）"
        label = f"👤 {rep}　｜　{v['status']}　｜　{v['visit_date'] or '-'}\n\n{content}"
        if st.button(label, key=f"rec_{v['id']}", use_container_width=True):
            _goto(sel_record=v["id"])


def _view_record_detail(industry, company, record_id):
    c1, c2 = st.columns([1, 5])
    if c1.button("← 記録一覧へ", use_container_width=True):
        _goto(sel_record=None)
    v = database.get_visit(record_id)
    if not v:
        st.info("記録が見つかりません。")
        return
    c2.header(f"👤 {v['rep_name'] or '（担当者不明）'}")
    st.caption(f"{v['industry']} / {v['company_name'] or NO_COMPANY}")
    _edit_form(record_id)


# ============================================================ 編集フォーム
def _edit_form(visit_id):
    v = database.get_visit(visit_id)
    if not v:
        return

    # 会社HPをウェブ検索して事業概要を取得（フォーム外＝押すと即反映）
    if _has_api_key() and st.button("🌐 会社HPから事業概要を取得", key=f"web_ov_{visit_id}"):
        try:
            with st.spinner("会社HPを検索して事業概要を作成中..."):
                ov = extractor.overview_from_web(v["company_name"], v["email"], v["address"], v["website"])
            if ov:
                database.update_visit(visit_id, business_overview=ov)
                st.success("HPから事業概要を取得しました。")
                st.rerun()
            else:
                st.warning("事業概要を特定できませんでした。")
        except Exception as e:  # noqa: BLE001
            st.error(f"取得に失敗しました: {e}")

    with st.form(f"edit_{visit_id}"):
        c0, c1 = st.columns(2)
        cur_ind = v["industry"] if v["industry"] in INDUSTRIES else INDUSTRIES[-1]
        industry = c0.selectbox("業界", INDUSTRIES, index=INDUSTRIES.index(cur_ind), key=f"ind_sel_{visit_id}")
        company = c1.text_input("会社名", v["company_name"])
        rep = st.text_input("担当者名", v["rep_name"])
        overview = st.text_area("事業概要（何をしている会社か）", v["business_overview"], height=80)
        content = st.text_area("営業内容（今回の売り込み）", v["sales_content"], height=120)
        c2, c3, c4 = st.columns(3)
        phone = c2.text_input("電話", v["phone"])
        email = c3.text_input("メール", v["email"])
        status = c4.selectbox("状態", STATUSES, index=STATUSES.index(v["status"]) if v["status"] in STATUSES else 0)
        website = st.text_input("公式HP（URL）", v["website"], placeholder="https://...")
        address = st.text_input("住所", v["address"])
        c5, c6 = st.columns(2)
        visit_d = c5.text_input("訪問日 (YYYY-MM-DD)", v["visit_date"] or "")
        received_d = c6.text_input("受領日 (YYYY-MM-DD)", v["received_date"] or "")
        memo = st.text_area("メモ", v["memo"], height=80)

        col_save, col_del = st.columns([3, 1])
        saved = col_save.form_submit_button("💾 保存", use_container_width=True)
        deleted = col_del.form_submit_button("🗑 削除", use_container_width=True)

    if saved:
        database.update_visit(
            visit_id, industry=industry, company_name=company, rep_name=rep,
            business_overview=overview, sales_content=content, phone=phone, email=email,
            website=website, address=address, status=status, visit_date=visit_d or None,
            received_date=received_d or None, memo=memo,
        )
        # 業界・会社・営業日・担当者・要件が変わったら資料も再配置＆リネーム
        cur = database.get_visit(visit_id)
        new_path = storage.refile(cur)
        if new_path != cur["source_file"]:
            database.update_visit(visit_id, source_file=new_path)
        st.success("保存しました")
        st.rerun()
    if deleted:
        database.delete_visit(visit_id)
        st.warning("削除しました")
        _goto(sel_record=None)

    _attachment_section(v)


def _attachment_section(v):
    """記録に紐づく資料（PDF/画像）を閲覧・添付する。"""
    visit_id = v["id"]
    src = v.get("source_file")
    p = Path(src) if src else None

    st.markdown("**📎 資料**")
    if p and p.exists():
        group = storage.group_files(str(p))
        _slideshow(group, visit_id)
        _bulk_download(group, v)
        st.divider()
        if st.button("この資料の紐付けを解除", key=f"unlink_{visit_id}"):
            database.update_visit(visit_id, source_file="")
            st.rerun()
        return

    if src and not (p and p.exists()):
        st.warning(f"資料ファイルが見つかりません: {src}")

    st.info("この記録には資料が添付されていません。フォルダの資料を選ぶか、アップロードして添付できます。")

    # 1) INBOX フォルダに置かれた資料から選んで添付
    inbox_files = importer.scan_inbox()
    if inbox_files:
        names = [f.name for f in inbox_files]
        pick = st.selectbox("フォルダ内の資料から選ぶ", names, key=f"pick_{visit_id}")
        if st.button("この資料を添付", key=f"attach_pick_{visit_id}"):
            dest = storage.store_move(INBOX_DIR / pick, v)
            database.update_visit(visit_id, source_file=dest)
            st.success(f"添付しました（{Path(dest).name}）")
            st.rerun()
    else:
        st.caption(f"（監視フォルダ {INBOX_DIR} に資料はありません）")

    # 2) アップロードして添付（業界/会社のフォルダへ保存）
    up = st.file_uploader(
        "アップロードして添付", type=[e.lstrip(".") for e in SUPPORTED_EXTS],
        key=f"up_{visit_id}",
    )
    if up is not None and st.button("アップロードした資料を添付", key=f"attach_up_{visit_id}"):
        dest = storage.store_bytes(up.name, bytes(up.getbuffer()), v)
        database.update_visit(visit_id, source_file=dest)
        st.success(f"添付しました（保存先: {dest}）")
        st.rerun()


@st.cache_data(show_spinner=False)
def _pdf_page_count(path, mtime):
    """PDF の総ページ数を返す（mtime でキャッシュ更新）。"""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


@st.cache_data(show_spinner=False)
def _render_pdf_page(path, mtime, index, scale=2.0):
    """PDF の指定ページだけを PNG バイト列に変換して返す。

    スライド表示では今見ているページしか要らないので1枚ずつ変換する。
    全ページを先に変換すると重いPDFで待たされるため。
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        pil = pdf[index].render(scale=scale).to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()


def _build_slides(files):
    """資料群を「1枚ずつめくれる」スライドの一覧に展開する。

    画像は1ファイル=1スライド、PDFは1ページ=1スライド。
    """
    slides = []
    for f in files:
        if f.suffix.lower() != ".pdf":
            slides.append({"kind": "image", "file": f})
            continue
        try:
            total = _pdf_page_count(str(f), f.stat().st_mtime)
        except Exception as e:  # noqa: BLE001
            slides.append({"kind": "error", "file": f, "msg": str(e)})
            continue
        for i in range(total):
            slides.append({"kind": "pdf", "file": f, "page": i, "pages": total})
    return slides


def _slide_label(s):
    """スライド下に出す説明文（ファイル名／PDFはページ番号つき）。"""
    if s["kind"] == "pdf":
        return f"{s['file'].name}（p.{s['page'] + 1}/{s['pages']}）"
    return s["file"].name


def _slideshow(files, visit_id):
    """資料をまとめて1つのスライドショーで表示する（◀ ▶ でめくる）。"""
    slides = _build_slides(files)
    if not slides:
        st.info("表示できる資料がありません。")
        return

    n = len(slides)
    key = f"slide_{visit_id}"
    idx = min(max(st.session_state.get(key, 0), 0), n - 1)

    if n > 1:
        c_prev, c_mid, c_next = st.columns([1, 4, 1])
        if c_prev.button("◀ 前へ", key=f"prev_{visit_id}", use_container_width=True):
            idx = (idx - 1) % n
        if c_next.button("次へ ▶", key=f"next_{visit_id}", use_container_width=True):
            idx = (idx + 1) % n
        st.session_state[key] = idx
        c_mid.markdown(
            f"<div style='text-align:center;padding-top:0.4rem'>"
            f"<b>{idx + 1} / {n}</b></div>",
            unsafe_allow_html=True,
        )

    s = slides[idx]
    f = s["file"]
    if s["kind"] == "error":
        st.error(f"PDFのプレビュー生成に失敗しました: {s['msg']}")
        st.caption("下の『ダウンロード』から開いてください。")
    elif s["kind"] == "pdf":
        with st.spinner("PDFを表示用に変換中..."):
            st.image(
                _render_pdf_page(str(f), f.stat().st_mtime, s["page"]),
                use_container_width=True,
            )
    else:
        st.image(str(f), use_container_width=True)

    st.caption(_slide_label(s))

    # 枚数が多いときは目的のスライドへ直接飛べるようにする。
    # key を渡さず value に idx+1 を渡すことで、◀▶ の移動にも追従させる。
    if n > 3:
        pos = st.slider("表示位置", 1, n, idx + 1, label_visibility="collapsed")
        if pos - 1 != idx:
            st.session_state[key] = pos - 1
            st.rerun()


@st.cache_data(show_spinner=False)
def _zip_bytes(entries):
    """資料群を1つのZIPにまとめる。entries は (パス, mtime) のタプル列。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, _mtime in entries:
            z.write(path, arcname=Path(path).name)
    return buf.getvalue()


def _bulk_download(files, v):
    """資料をまとめて1回でダウンロードできるボタン（複数ならZIP）。"""
    if not files:
        return
    visit_id = v["id"]
    if len(files) == 1:
        f = files[0]
        st.download_button(
            f"⬇️ ダウンロード（{f.name}）", f.read_bytes(),
            file_name=f.name, key=f"dl_{visit_id}", use_container_width=True,
        )
        return
    entries = tuple((str(f), f.stat().st_mtime) for f in files)
    st.download_button(
        f"⬇️ すべてダウンロード（{len(files)}件・ZIP）",
        _zip_bytes(entries),
        file_name=storage.build_filename(v, ".zip"),
        mime="application/zip",
        key=f"dlzip_{visit_id}",
        use_container_width=True,
    )


# ============================================================ 一覧（全件・検索）
def page_all():
    st.header("📋 営業一覧（全件・検索）")
    c1, c2, c3 = st.columns([1, 1, 2])
    industry = c1.selectbox("業界", ["すべて"] + INDUSTRIES)
    status = c2.selectbox("ステータス", STATUS_FILTER)
    keyword = c3.text_input("キーワード検索（会社名・担当者・営業内容）")

    rows = database.get_visits(
        status=status,
        keyword=keyword or None,
        industry=None if industry == "すべて" else industry,
    )
    st.caption(f"{len(rows)} 件　—　行をクリックするとその記録の詳細画面へ移動します。")
    if rows:
        df = pd.DataFrame(rows)[[
            "id", "industry", "company_name", "rep_name", "sales_content",
            "visit_date", "status",
        ]].rename(columns={
            "id": "ID", "industry": "業界", "company_name": "会社名", "rep_name": "担当者",
            "sales_content": "営業内容", "visit_date": "訪問日", "status": "状態",
        })
        event = st.dataframe(
            df, use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row", key="all_df",
        )
        selected = event.selection.rows if event and event.selection else []
        if selected:
            _jump_to_record(rows[selected[0]])
    else:
        st.info("該当なし。")

    with st.expander("➕ 手動で追加"):
        _add_form()


def _jump_to_record(rec):
    """営業一覧から、その記録の詳細画面（業界→会社→記録）へ遷移する。"""
    st.session_state["sel_industry"] = rec["industry"]
    st.session_state["sel_company"] = rec["company_name"]
    st.session_state["sel_record"] = rec["id"]
    st.session_state["_jump_browse"] = True  # サイドバーを「業界から探す」に切替
    st.session_state.pop("all_df", None)     # 選択状態をリセット（戻ったとき再発火を防ぐ）
    st.rerun()


def _add_form():
    with st.form("add_manual"):
        c0, c1 = st.columns(2)
        industry = c0.selectbox("業界", INDUSTRIES)
        company = c1.text_input("会社名 *")
        rep = st.text_input("担当者名")
        overview = st.text_area("事業概要（何をしている会社か）")
        content = st.text_area("営業内容（今回の売り込み）")
        c2, c3 = st.columns(2)
        phone = c2.text_input("電話")
        email = c3.text_input("メール")
        visit_d = st.text_input("訪問日 (YYYY-MM-DD)", date.today().isoformat())
        if st.form_submit_button("追加"):
            if not company.strip():
                st.error("会社名は必須です")
            else:
                database.add_visit(
                    industry=industry, company_name=company, rep_name=rep,
                    business_overview=overview, sales_content=content, phone=phone, email=email,
                    visit_date=visit_d or None, status="確認済",
                )
                st.success("追加しました")
                st.rerun()


# ============================================================ 営業記録の作成
_REC_FIELDS = ("r_company", "r_rep", "r_overview", "r_content", "r_phone", "r_email", "r_website", "r_address")


def page_record():
    st.header("📝 営業記録の作成")
    st.caption(
        "業界と営業日を選び、営業資料（PDF・画像・名刺、複数可）をアップロードして"
        "『資料から読み取る』を押すと、会社名・担当者・事業概要・営業内容などが自動でフォームに入ります。"
        "内容を確認・修正して登録すると、営業一覧および該当の業界・会社に格納されます。"
    )

    for k in _REC_FIELDS:
        st.session_state.setdefault(k, "")
    st.session_state.setdefault("rec_uploader_id", 0)
    # HP検索で取得した事業概要を、フォーム描画前に反映
    if "_pending_overview" in st.session_state:
        st.session_state["r_overview"] = st.session_state.pop("_pending_overview")

    # --- こちらで選ぶ項目 ---
    c1, c2 = st.columns(2)
    industry = c1.selectbox("業界 *（選択）", INDUSTRIES, key="r_industry")
    visit_date = c2.date_input("営業日 *（選択）", value=date.today(), key="r_visit_date")

    # --- 資料アップロード ---
    uploader_key = f"rec_files_{st.session_state['rec_uploader_id']}"
    files = st.file_uploader(
        "営業資料をアップロード（PDF・画像・名刺、複数可）",
        type=[e.lstrip(".") for e in SUPPORTED_EXTS],
        accept_multiple_files=True, key=uploader_key,
    )
    if not _has_api_key():
        st.info("ANTHROPIC_API_KEY 未設定のため自動読み取りは使えません。フォームに直接入力して登録できます。")

    if st.button("📖 資料から読み取ってフォームに反映", disabled=not (_has_api_key() and files)):
        try:
            with st.spinner("Claude API で資料を解析中..."):
                data = extractor.extract_uploads([(f.name, f.getvalue()) for f in files])
            st.session_state["r_company"] = data.get("company_name", "")
            st.session_state["r_rep"] = data.get("rep_name", "")
            st.session_state["r_overview"] = data.get("business_overview", "")
            st.session_state["r_content"] = data.get("sales_content", "")
            st.session_state["r_phone"] = data.get("phone", "")
            st.session_state["r_email"] = data.get("email", "")
            st.session_state["r_website"] = data.get("website", "")
            st.session_state["r_address"] = data.get("address", "")
            st.success("資料から読み取りました。内容を確認・修正して登録してください。")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"読み取りに失敗しました: {e}")

    # --- フォーム（資料から自動入力／手入力も可） ---
    st.divider()
    st.subheader("営業記録フォーム")
    st.text_input("会社名 *", key="r_company")
    st.text_input("担当者名", key="r_rep")
    st.text_area("事業概要（何をしている会社か）", key="r_overview", height=80)
    st.text_area("営業内容（今回の売り込み）", key="r_content", height=120)
    cc1, cc2 = st.columns(2)
    cc1.text_input("電話", key="r_phone")
    cc2.text_input("メール", key="r_email")
    st.text_input("公式HP（URL）", key="r_website", placeholder="https://...")
    st.text_input("住所", key="r_address")

    # 会社HPをウェブ検索して事業概要を自動生成
    if st.button("🌐 会社HPから事業概要を取得（会社名で検索）",
                 disabled=not (_has_api_key() and st.session_state["r_company"].strip())):
        try:
            with st.spinner("会社HPを検索して事業概要を作成中..."):
                ov = extractor.overview_from_web(
                    st.session_state["r_company"], st.session_state["r_email"],
                    st.session_state["r_address"], st.session_state["r_website"],
                )
            if ov:
                st.session_state["_pending_overview"] = ov
                st.rerun()
            else:
                st.warning("事業概要を特定できませんでした。会社名を確認して再試行するか、手入力してください。")
        except Exception as e:  # noqa: BLE001
            st.error(f"取得に失敗しました: {e}")

    if st.button("✅ この内容で営業記録を登録", type="primary"):
        if not st.session_state["r_company"].strip():
            st.error("会社名は必須です。資料から読み取るか、手入力してください。")
        else:
            _register_record(industry, visit_date, files)


def _register_record(industry, visit_date, files):
    vd = visit_date.isoformat() if hasattr(visit_date, "isoformat") else str(visit_date)
    visit_id = database.add_visit(
        industry=industry,
        company_name=st.session_state["r_company"],
        rep_name=st.session_state["r_rep"],
        business_overview=st.session_state["r_overview"],
        sales_content=st.session_state["r_content"],
        phone=st.session_state["r_phone"],
        email=st.session_state["r_email"],
        website=st.session_state["r_website"],
        address=st.session_state["r_address"],
        visit_date=vd,
        received_date=date.today().isoformat(),
        status="確認済",
    )
    record = database.get_visit(visit_id)

    saved = []
    if files:
        for f in files:
            try:
                saved.append(storage.store_bytes(f.name, bytes(f.getvalue()), record))
            except Exception as e:  # noqa: BLE001
                st.warning(f"{f.name} の保存に失敗: {e}")
        if saved:
            primary = next((p for p in saved if p.lower().endswith(".pdf")), saved[0])
            database.update_visit(visit_id, source_file=primary)

    for k in _REC_FIELDS:
        st.session_state.pop(k, None)
    st.session_state["rec_uploader_id"] += 1

    n = len(saved)
    st.success(
        f"営業記録を登録しました（{industry} / {record['company_name']}）。"
        + (f" 資料 {n} 件を保存。" if n else "")
        + " 『業界から探す』『営業一覧』に反映されます。"
    )
    st.rerun()


# ============================================================ ダッシュボード
def page_dashboard():
    st.header("📊 ダッシュボード")
    s = database.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("総件数", s["total"])
    c2.metric("今月の件数", s["this_month"])
    c3.metric("要対応（下書き＋対応中）", s["by_status"].get("下書き", 0) + s["by_status"].get("対応中", 0))

    rows = database.get_visits()
    if not rows:
        st.info("データがありません。")
        return
    df = pd.DataFrame(rows)
    try:
        import plotly.express as px
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("業界別 件数")
            ind = df["industry"].value_counts().reset_index()
            ind.columns = ["業界", "件数"]
            st.plotly_chart(px.bar(ind, x="件数", y="業界", orientation="h"), use_container_width=True)
        with col2:
            st.subheader("ステータス別")
            st.plotly_chart(px.pie(df, names="status", hole=0.4), use_container_width=True)
    except Exception:
        st.bar_chart(df["industry"].value_counts())


# ============================================================ ナビ
PAGES = {
    "業界から探す": page_browse,
    "営業記録の作成": page_record,
    "営業一覧（全件・検索）": page_all,
    "ダッシュボード": page_dashboard,
}

st.sidebar.title("🧑‍💼 営業訪問者 管理")
# 営業一覧からの「詳細へジャンプ」要求があれば、ラジオ生成前に画面を切り替える
if st.session_state.pop("_jump_browse", False):
    st.session_state["nav"] = "業界から探す"
choice = st.sidebar.radio("画面", list(PAGES.keys()), key="nav")
_s = database.stats()
draft = _s["by_status"].get("下書き", 0)
if draft:
    st.sidebar.warning(f"未確認（下書き）: {draft} 件")
st.sidebar.caption(f"総件数: {_s['total']}")
PAGES[choice]()
