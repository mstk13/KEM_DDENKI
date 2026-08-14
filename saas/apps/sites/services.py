"""現場管理のビジネスロジック。

現場の集計・ステータス管理と、既にある現場への見積ファイル反映を担う。
将来の DRF API 移行時にもそのまま使える。
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Avg, Sum

from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import Customer
from apps.sites.importer import normalize_company_name


def find_customer_by_name(company, raw_name):
    """見積書の宛名から得意先マスタを引き当てる。見つからなければ None。

    「株式会社ABC」「(株)ABC」「㈱ ABC」を同じものとして扱う。
    自動作成はしない — 表記ゆれで重複マスタが増えるほうが後で困るため、
    未登録なら確認画面で人に選んでもらう。
    """
    if not raw_name:
        return None

    key = normalize_company_name(raw_name)
    if not key:
        return None

    # unscoped: テナントコンテキスト未設定の取り込み経路からも使うため、
    # company を明示して絞る。
    for customer in Customer.unscoped.filter(company=company, is_active=True):
        if normalize_company_name(customer.name) == key:
            return customer
    return None


def get_site_summary(site):
    """現場のサマリ情報を取得する。"""
    total_cost = (
        CostTransaction.unscoped.filter(site=site)
        .aggregate(t=Sum("amount"))["t"]
        or 0
    )
    budget_total = (
        BudgetItem.unscoped.filter(site=site)
        .aggregate(t=Sum("amount"))["t"]
        or 0
    )
    gross_profit = site.contract_amount - total_cost
    margin_rate = (
        round(float(gross_profit / site.contract_amount * 100), 1)
        if site.contract_amount
        else None
    )
    phase_progress = (
        site.phases.aggregate(avg=Avg("progress"))["avg"] or 0
    )

    return {
        "total_cost": total_cost,
        "budget_total": budget_total,
        "gross_profit": gross_profit,
        "margin_rate": margin_rate,
        "phase_progress": int(phase_progress),
        "worker_count": site.assignments.values("worker").distinct().count(),
        "report_count": site.daily_reports.count(),
    }


# ---------------------------------------------------------------------------
# 既にある現場への見積ファイル反映
# ---------------------------------------------------------------------------
#
# 落札や受注のフェーズ移行で自動作成された現場は、名前と概算金額しか入って
# いない。そこへ後からライデンの Excel / CSV や見積書 PDF を入れて数字を
# 埋められるようにする。新規登録の取り込みと違い、**項目ごとに反映するかを
# 人が選ぶ**。現場側で直した値をファイルの内容で黙って上書きしないため。

# 反映できる項目と画面上の名前。表示順もこの通り。
APPLY_FIELDS: tuple[tuple[str, str], ...] = (
    ("code", "現場コード（見積番号）"),
    ("name", "現場名（工事件名）"),
    ("customer", "得意先"),
    ("contract_amount", "受注金額"),
    ("payment_terms", "支払条件"),
    ("address", "施工場所"),
    ("start_date", "工期開始"),
    ("end_date", "工期終了"),
    ("estimate_valid_until", "見積有効期限"),
    ("note", "備考"),
    ("extracted_details", "その他の読み取り項目"),
)

# 備考とその他の読み取り項目は置き換えず追記する。現場側で書いた申し送りが
# 取り込みで消えると、日報を書く人が見るべき情報を失う。
_APPEND_FIELDS = frozenset({"note", "extracted_details"})

# CharField の項目は長さ超過で保存に失敗するため、入れる前に切る。
# ここに無い項目（address などの TextField）は切らずにそのまま入れる。
_MAX_LENGTHS = {
    "code": 50,
    "name": 200,
    "payment_terms": 200,
    "estimate_valid_until": 100,
}


def _customer_or_none(company, raw_pk):
    """得意先の pk 文字列から得意先を引く。他社のものは引かない。"""
    if not str(raw_pk).isdigit():
        return None
    # unscoped: 取り込み経路はテナントコンテキスト未設定で通ることがあるため
    # company を明示して絞る。
    return Customer.unscoped.filter(company=company, pk=int(raw_pk)).first()


def _parse_amount(raw):
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_iso_date(raw):
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        return None


def _append_text(current: str, addition: str) -> str:
    """既にある行は足さない。同じファイルを2回入れても行が増殖しないように。"""
    existing = {line.strip() for line in current.splitlines() if line.strip()}
    added = [
        line for line in addition.splitlines()
        if line.strip() and line.strip() not in existing
    ]
    if not added:
        return current
    if not current.strip():
        return "\n".join(added)
    return current.rstrip() + "\n" + "\n".join(added)


def estimate_values_for_site(parsed, matched_customer=None) -> dict[str, str]:
    """読み取り結果を「現場のどの項目に、どんな値で入るか」に直す。

    読めなかった項目はキーごと落とす。空文字で上書きする事故を作らないため、
    「読めなかった」と「空にしたい」を混ぜない。
    確認画面のフォームを往復するので、値はすべて文字列で持つ。
    """
    values: dict[str, str] = {}

    for key in ("code", "name", "payment_terms", "address",
                "estimate_valid_until", "note"):
        text = (parsed.get(key) or "").strip()
        if text:
            values[key] = text

    amount = parsed.get("contract_amount")
    if amount not in (None, ""):
        values["contract_amount"] = str(amount)

    for key in ("start_date", "end_date"):
        if parsed.get(key):
            values[key] = str(parsed[key])

    if matched_customer is not None:
        values["customer"] = str(matched_customer.pk)

    details = parsed.get("details") or []
    if details:
        values["extracted_details"] = "\n".join(
            f"{label}: {value}" for label, value in details
        )

    return values


def _new_display(field, raw, company) -> str:
    """反映後にどう表示されるか。現在値と突き合わせて差分を判定するのに使う。"""
    if field == "customer":
        customer = _customer_or_none(company, raw)
        return customer.name if customer else ""
    return str(raw)


def _current_display(site, field) -> str:
    """現在の値の表示。_new_display と同じ書式にそろえる。"""
    if field == "customer":
        return site.customer.name if site.customer_id else ""
    if field == "contract_amount":
        amount = site.contract_amount or 0
        return "" if amount == 0 else str(int(amount))
    return str(getattr(site, field) or "")


def build_estimate_diff(site, values, company) -> list[dict]:
    """項目ごとに「現在の値」と「ファイルの値」を並べた行を作る。

    既に値がある項目は既定でチェックを外す。自動作成された現場の空欄だけが
    既定で入り、人が入れた値は選ばないかぎり変わらない。
    """
    rows = []
    for field, label in APPLY_FIELDS:
        if field not in values:
            continue
        new_display = _new_display(field, values[field], company)
        if not new_display:
            # 得意先を引き当てられなかった等。出しても選べないので落とす。
            continue
        current = _current_display(site, field)

        if field in _APPEND_FIELDS:
            # 追記なので既存の値は消えない。まだ書かれていなければ既定で入れる。
            unchanged = bool(current) and _append_text(current, new_display) == current
            checked = not unchanged
        else:
            unchanged = current == new_display
            checked = not current

        rows.append({
            "field": field,
            "label": label,
            "current": current,
            "value": values[field],
            "new_display": new_display,
            "unchanged": unchanged,
            "checked": checked,
            "is_append": field in _APPEND_FIELDS,
        })
    return rows


def apply_estimate_to_site(site, values, selected_fields, company) -> list[str]:
    """選ばれた項目だけを現場へ反映する。反映した項目名のリストを返す。

    値を解釈できなかった項目は飛ばす（戻り値にも入らない）ので、画面には
    「何が実際に入ったか」だけが出る。
    """
    applied: list[str] = []
    updated: list[str] = []

    for field, label in APPLY_FIELDS:
        if field not in selected_fields or field not in values:
            continue
        raw = values[field]

        if field == "customer":
            customer = _customer_or_none(company, raw)
            if customer is None:
                continue
            site.customer = customer
        elif field == "contract_amount":
            amount = _parse_amount(raw)
            if amount is None:
                continue
            site.contract_amount = amount
        elif field in ("start_date", "end_date"):
            parsed_date = _parse_iso_date(raw)
            if parsed_date is None:
                continue
            setattr(site, field, parsed_date)
        elif field in _APPEND_FIELDS:
            merged = _append_text(getattr(site, field) or "", str(raw))
            if merged == (getattr(site, field) or ""):
                continue
            setattr(site, field, merged)
        else:
            limit = _MAX_LENGTHS.get(field)
            setattr(site, field, str(raw)[:limit] if limit else str(raw))

        updated.append(field)
        applied.append(label)

    if updated:
        # auto_now の updated_at は update_fields に入れないと更新されない。
        site.save(update_fields=[*updated, "updated_at"])
    return applied
