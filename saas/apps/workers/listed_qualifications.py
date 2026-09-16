"""資格保有一覧（ケンモチ電機 資格保有一覧、2026/9/15）の資格を、作業員ごとに登録する（ADR-0068）。

原本: 「資格保有一覧.xls」のシート「ケンモチ電機　資格保有一覧」（14 人・150 件）。
このファイルの資格名・区分・○の位置は、その Excel から機械的に書き出したもの。

- 「○」の資格を、その作業員の保有資格（WorkerQualification）として資格名と区分だけ登録する。
  取得日・有効期限・原本の写真は、あとから作業員の画面で入れる
- 資格名は Excel の見出しのまま（「電気工事施工監理技士　１級」など）。
  見出しの「(補△)」は凡例なので資格名からは外し、「△」の人は「（補）」を付けて登録する
- 区分は Excel の種別に合わせる（免許・免状 / 技能講習修了証 / 特別教育修了証 / その他）
- シート「ダイト空調 資格保有一覧」は他社なので登録しない

作業員は氏名で探す。空白の有無と、髙→高・榮→栄・釼→剣 のような字の違いは同じとみなす。
同じ作業員に同じ資格名が既にあれば登録しない（何度流しても増えない）。
このファイルから登録した資格のうち、一覧に無くなったものは消す（前に別の表記で登録したものを含む）。
手で登録した資格（備考が違う）は消さない。

データ移送（workers/0018・0019）と管理コマンド register_listed_qualifications の両方から使う。
データ移送からは履歴モデルを渡すので、モデルは引数で受け取り、
テナントで絞らない _base_manager を使う。
"""

SOURCE = "資格保有一覧.xls（2026/9/15）"
NOTE = f"{SOURCE}から登録。原本の写真は未添付"
# 前に PDF の「資格保有状況一覧」から登録したときの備考。入れ替えのときに消す目印にする
PREVIOUS_NOTES = ("資格保有状況一覧（2026/9/15）から登録。原本の写真は未添付",)
COMPANY_NAME = "ケンモチ電機"

LICENSE = "license"
SKILL_COURSE = "skill_course"
EDUCATION = "education"
OTHER = "other"

# 資格名 → 区分（Excel の列の並び）
CATEGORIES = {
    # 免許・免状
    "電気工事施工監理技士　１級": LICENSE,
    "電気工事施工監理技士　１級（補）": LICENSE,
    "電気工事施工監理技士　２級": LICENSE,
    "土木施工監理技士　１級": LICENSE,
    "登録電気工事基幹技能者": LICENSE,
    "電気工事士　1種": LICENSE,
    "電気工事士　2種": LICENSE,
    "特種電気工事士 非常用予備発電装置工事": LICENSE,
    "第二種あと施工アンカー": LICENSE,
    "クレーン・デリック運転士": LICENSE,
    "運転免許証": LICENSE,
    "監理技術者": LICENSE,
    "一般建築物石綿含有建材調査者": LICENSE,
    # 技能講習修了証
    "石綿作業主任者": SKILL_COURSE,
    "高所作業車・作業床高⒑ｍ以上": SKILL_COURSE,
    "高圧ケーブル工事": SKILL_COURSE,
    "車両系建設機械(整地)3t以上": SKILL_COURSE,
    "移動式クレーン": SKILL_COURSE,
    "玉掛け・吊上げ荷重1ｔ以上": SKILL_COURSE,
    "足場の組立て等作業主任者": SKILL_COURSE,
    "鉄骨の組立て等作業主任者": SKILL_COURSE,
    "地中線用ＧＲ付高圧負荷開閉器施工技術者": SKILL_COURSE,
    "職長・安全衛生責任者教育": SKILL_COURSE,
    "酸素欠乏・硫化水素 危険作業 主任者": SKILL_COURSE,
    "引込線": SKILL_COURSE,
    "引込線請負工事卓上講習": SKILL_COURSE,
    # 特別教育修了証
    "車両系建設機械・機重３ｔ未満": EDUCATION,
    "小型移動式クレーン": EDUCATION,
    "アーク溶接": EDUCATION,
    "石綿取扱作業従事者": EDUCATION,
    "フルハーネス": EDUCATION,
    "ガス溶接": EDUCATION,
    "建設用リフト": EDUCATION,
    # その他
    "ケーブル延焼防止材による防火措置": OTHER,
    "3M工法取得認定（高圧端末 常温収縮）": OTHER,
}

# 氏名 → 保有資格（Excel の行の並び。資格は Excel の列の並び）
HOLDERS = {
    "釼持　陽子": [
        "電気工事施工監理技士　１級", "登録電気工事基幹技能者", "電気工事士　1種",
        "電気工事士　2種", "特種電気工事士 非常用予備発電装置工事", "運転免許証", "監理技術者",
        "一般建築物石綿含有建材調査者", "石綿作業主任者", "高所作業車・作業床高⒑ｍ以上",
        "高圧ケーブル工事", "車両系建設機械(整地)3t以上",
        "地中線用ＧＲ付高圧負荷開閉器施工技術者", "職長・安全衛生責任者教育", "引込線",
        "引込線請負工事卓上講習", "石綿取扱作業従事者", "フルハーネス",
        "3M工法取得認定（高圧端末 常温収縮）",
    ],
    "釼持　政宏": [
        "電気工事施工監理技士　１級（補）", "登録電気工事基幹技能者", "電気工事士　1種",
        "電気工事士　2種", "特種電気工事士 非常用予備発電装置工事", "第二種あと施工アンカー",
        "クレーン・デリック運転士", "運転免許証", "一般建築物石綿含有建材調査者",
        "石綿作業主任者", "高所作業車・作業床高⒑ｍ以上", "高圧ケーブル工事",
        "車両系建設機械(整地)3t以上", "玉掛け・吊上げ荷重1ｔ以上",
        "地中線用ＧＲ付高圧負荷開閉器施工技術者", "職長・安全衛生責任者教育", "引込線",
        "引込線請負工事卓上講習", "アーク溶接", "石綿取扱作業従事者", "フルハーネス",
        "ケーブル延焼防止材による防火措置", "3M工法取得認定（高圧端末 常温収縮）",
    ],
    "高橋　章": [
        "電気工事士　1種", "電気工事士　2種", "運転免許証", "高所作業車・作業床高⒑ｍ以上",
        "高圧ケーブル工事", "玉掛け・吊上げ荷重1ｔ以上", "職長・安全衛生責任者教育", "引込線",
        "車両系建設機械・機重３ｔ未満", "小型移動式クレーン", "フルハーネス",
    ],
    "江頭　敏幸": [
        "電気工事士　1種", "電気工事士　2種", "運転免許証", "高所作業車・作業床高⒑ｍ以上",
        "高圧ケーブル工事", "職長・安全衛生責任者教育", "酸素欠乏・硫化水素 危険作業 主任者",
        "引込線", "車両系建設機械・機重３ｔ未満", "小型移動式クレーン", "アーク溶接",
        "フルハーネス",
    ],
    "片桐　徳男": [
        "電気工事施工監理技士　１級", "電気工事士　1種", "電気工事士　2種",
        "特種電気工事士 非常用予備発電装置工事", "運転免許証", "監理技術者",
        "高所作業車・作業床高⒑ｍ以上", "高圧ケーブル工事", "職長・安全衛生責任者教育",
        "引込線請負工事卓上講習",
    ],
    "茨木　浩次": [
        "電気工事士　1種", "電気工事士　2種", "高所作業車・作業床高⒑ｍ以上", "高圧ケーブル工事",
        "引込線", "アーク溶接", "石綿取扱作業従事者", "フルハーネス", "ガス溶接",
    ],
    "出永　修": [
        "電気工事士　1種", "電気工事士　2種", "運転免許証", "高所作業車・作業床高⒑ｍ以上",
        "高圧ケーブル工事", "玉掛け・吊上げ荷重1ｔ以上", "職長・安全衛生責任者教育", "引込線",
        "小型移動式クレーン", "ガス溶接",
    ],
    "佐藤　榮一": [
        "電気工事施工監理技士　２級", "電気工事士　1種", "電気工事士　2種", "運転免許証",
        "高所作業車・作業床高⒑ｍ以上", "高圧ケーブル工事", "玉掛け・吊上げ荷重1ｔ以上",
        "足場の組立て等作業主任者", "鉄骨の組立て等作業主任者", "職長・安全衛生責任者教育",
        "酸素欠乏・硫化水素 危険作業 主任者", "引込線", "小型移動式クレーン", "アーク溶接",
        "フルハーネス", "ガス溶接",
    ],
    "古矢　隆": [
        "電気工事施工監理技士　１級", "電気工事士　1種", "電気工事士　2種", "監理技術者",
        "高所作業車・作業床高⒑ｍ以上", "高圧ケーブル工事", "移動式クレーン",
        "玉掛け・吊上げ荷重1ｔ以上", "職長・安全衛生責任者教育", "引込線", "小型移動式クレーン",
    ],
    "村井　君好": [
        "電気工事施工監理技士　１級", "土木施工監理技士　１級", "電気工事士　1種",
        "電気工事士　2種", "運転免許証", "監理技術者", "玉掛け・吊上げ荷重1ｔ以上",
        "酸素欠乏・硫化水素 危険作業 主任者", "小型移動式クレーン", "アーク溶接", "ガス溶接",
        "建設用リフト",
    ],
    "髙橋　翔太": [
        "運転免許証", "職長・安全衛生責任者教育",
    ],
    "杉本　和幸": [
        "電気工事士　2種", "運転免許証", "石綿作業主任者", "高所作業車・作業床高⒑ｍ以上",
        "足場の組立て等作業主任者", "酸素欠乏・硫化水素 危険作業 主任者", "引込線",
    ],
    "梅田　義彦": [
        "電気工事施工監理技士　１級", "土木施工監理技士　１級", "電気工事士　2種", "運転免許証",
        "玉掛け・吊上げ荷重1ｔ以上", "アーク溶接",
    ],
    "松倉　利昭": [
        "電気工事施工監理技士　１級", "電気工事士　1種",
    ],
}

# 氏名の字の違い（旧字・異体字）を揃える
_NAME_VARIANTS = str.maketrans({
    "髙": "高", "榮": "栄", "釼": "剣", "劔": "剣", "剱": "剣", "﨑": "崎", "德": "徳",
})


def normalize_person_name(name: str) -> str:
    """空白を除き、旧字・異体字を揃える。「髙橋　翔太」→「高橋翔太」。"""
    return "".join((name or "").split()).translate(_NAME_VARIANTS)


def find_company(Company):
    """登録先の会社。会社名「ケンモチ電機」、無ければ会社が1社だけのときのその会社。"""
    company = Company._base_manager.filter(name=COMPANY_NAME).order_by("pk").first()
    if company is not None:
        return company
    companies = list(Company._base_manager.order_by("pk")[:2])
    return companies[0] if len(companies) == 1 else None


def _our_notes():
    return (NOTE, *PREVIOUS_NOTES)


def register_listed_qualifications(company, Worker, WorkerQualification, *, apply=True):
    """一覧の資格を作業員ごとに登録し、一覧に無くなった資格を消す。

    消すのはこの一覧から登録した資格だけ（備考が一致するもの）。
    手で登録した資格や、写真を添えた別の資格はそのまま残す。

    Returns:
        {
            "created": [(作業員名, 資格名)],   … 登録した（apply=False なら登録する予定）
            "existing": [(作業員名, 資格名)],  … 既に同じ資格名があるので何もしない
            "removed": [(作業員名, 資格名)],   … 一覧に無いので消した（予定）
            "missing": [一覧の氏名],            … 作業員が見つからない
            "ambiguous": [一覧の氏名],          … 同じ氏名の在籍中の作業員が複数いる
        }
    """
    report = {"created": [], "existing": [], "removed": [], "missing": [], "ambiguous": []}
    if company is None:
        report["missing"] = list(HOLDERS)
        return report

    by_name = {}
    for worker in Worker._base_manager.filter(company=company).order_by("pk"):
        by_name.setdefault(normalize_person_name(worker.name), []).append(worker)

    for listed_name, names in HOLDERS.items():
        found = by_name.get(normalize_person_name(listed_name), [])
        if len(found) > 1:
            # 退職者と同姓同名なら在籍中の人にする
            found = [w for w in found if getattr(w, "is_active", True)] or found
        if not found:
            report["missing"].append(listed_name)
            continue
        if len(found) > 1:
            report["ambiguous"].append(listed_name)
            continue
        worker = found[0]
        wanted = set(names)
        held = set()
        for qual in WorkerQualification._base_manager.filter(worker=worker):
            if qual.name in wanted:
                held.add(qual.name)
                continue
            if qual.note in _our_notes():
                # この一覧から登録したが、一覧に無くなった資格（表記を直した分を含む）
                report["removed"].append((worker.name, qual.name))
                if apply:
                    qual.delete()
        for name in names:
            if name in held:
                report["existing"].append((worker.name, name))
                continue
            if apply:
                WorkerQualification._base_manager.create(
                    company=company, worker=worker, name=name,
                    category=CATEGORIES[name], note=NOTE,
                )
            held.add(name)
            report["created"].append((worker.name, name))
    return report
