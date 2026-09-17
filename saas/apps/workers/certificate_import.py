"""資格証のPDFを、作業員の保有資格に添付する（ADR-0082）。

フォルダの形:

    資格書一覧/
      釼持　政宏/
        第一種電気工事士免状.pdf
        高圧ケーブル工事技能認定証.pdf
        ...
      髙橋　翔太/
        運転免許証.pdf
      ...

- フォルダ名が作業員の氏名。空白の有無と旧字（髙→高・釼→剣 など）の違いは同じとみなす
- ファイル名から、登録済みの資格名（資格保有一覧の見出し。ADR-0068）に読み替えて添付する
- 同じ資格に複数のファイルがあるときは、優先度の高い1件だけ添付し、残りは報告に出す
- 「_資格書チェックリスト.pdf」は台紙なので添付しない
- 有効期限・取得日は、別に渡す CSV（氏名,ファイル名,取得日,有効期限）から入れる。
  期限の記載が無い修了証は、日付を空のままにする（プロダクトオーナーの指示、2026-09-17）
- 個人書類なのでファイルはリポジトリに置かない。サーバーにフォルダを置いて実行する
"""

import csv
import datetime
import pathlib

from django.core.files import File

from apps.workers.listed_qualifications import (
    CATEGORIES,
    EDUCATION,
    LICENSE,
    OTHER,
    SKILL_COURSE,
    normalize_person_name,
)

# 台紙（資格の一覧表）。添付の対象にしない
CHECKLIST_MARK = "チェックリスト"

# ファイル名（拡張子なし）→ (登録済みの資格名, 優先度)。
# 優先度は、同じ資格に複数のファイルがあるときにどれを添付するかを決める。大きいほう。
FILE_TO_QUALIFICATION = {
    "第一種電気工事士免状": ("電気工事士　1種", 1),
    "第二種電気工事士免状": ("電気工事士　2種", 1),
    "特種電気工事資格者認定証": ("特種電気工事士 非常用予備発電装置工事", 1),
    "登録電気工事基幹技能者講習修了証": ("登録電気工事基幹技能者", 1),
    "監理技術者資格者証": ("監理技術者", 1),
    "運転免許証": ("運転免許証", 1),
    "クレーン・デリック運転士免許証(クレーン限定)": ("クレーン・デリック運転士", 1),
    "あと施工アンカー認定資格登録証": ("第二種あと施工アンカー", 1),
    "高圧ケーブル工事技能認定証": ("高圧ケーブル工事", 1),
    "地中線用GR付高圧負荷開閉器施工技術認定証": (
        "地中線用ＧＲ付高圧負荷開閉器施工技術者", 1,
    ),
    "3M工法修得認定証": ("3M工法取得認定（高圧端末 常温収縮）", 1),
    "建築物石綿含有建材調査者講習修了証明書": ("一般建築物石綿含有建材調査者", 1),
    "石綿作業主任者技能講習修了証": ("石綿作業主任者", 1),
    "石綿(アスベスト)取扱作業従事者特別教育修了証": ("石綿取扱作業従事者", 1),
    "玉掛技能講習修了証": ("玉掛け・吊上げ荷重1ｔ以上", 1),
    "高所作業車運転技能講習修了証": ("高所作業車・作業床高⒑ｍ以上", 1),
    "車両系建設機械(整地)運転技能講習修了証": ("車両系建設機械(整地)3t以上", 1),
    "ケーブル延焼防止材による防火措置技能講習修了証": (
        "ケーブル延焼防止材による防火措置", 1,
    ),
    "フルハーネス型制止用器具取扱特別教育修了証": ("フルハーネス", 1),
    "職長・安全衛生責任者教育修了証": ("職長・安全衛生責任者教育", 1),
    "特別・職長教育修了証": ("職長・安全衛生責任者教育", 1),
    # 引込線の工事者証。1人に複数枚あるので、作業範囲の広いものを優先する
    "引込線(アンペアブレーカ)工事者証(柱上・地上作業)": ("引込線", 3),
    "引込線(アンペアブレーカ)工事者証": ("引込線", 2),
    "引込線(アンペアブレーカ)工事者証(地上作業のみ)": ("引込線", 1),
    "引込線(アンペアブレーカ)工事者証_講習受講欄": ("引込線", 0),
    # 資格保有一覧に見出しが無いもの。その作業員の保有資格として新しく作る
    "低圧電気取扱業務特別教育修了証": ("低圧電気取扱業務特別教育", 1),
    "電気取扱業務(特高・高圧)特別教育修了証": ("電気取扱業務（特別高圧・高圧）特別教育", 1),
    "高圧・特別高圧電気取扱業務特別教育修了証": (
        "電気取扱業務（特別高圧・高圧）特別教育", 2,
    ),
    "酸素欠乏・硫化水素危険作業特別教育修了証": ("酸素欠乏・硫化水素危険作業特別教育", 1),
    "産業廃棄物処理業許可申請講習会(更新・収集運搬課程)修了証": (
        "産業廃棄物処理業許可申請講習会（更新・収集運搬課程）", 1,
    ),
}

# 資格保有一覧に無い資格の区分。名前に含まれる語で決める
_CATEGORY_WORDS = (
    ("免状", LICENSE),
    ("免許", LICENSE),
    ("技能講習", SKILL_COURSE),
    ("特別教育", EDUCATION),
    ("教育", EDUCATION),
)


def category_for(qualification_name: str) -> str:
    """資格の区分。資格保有一覧にある資格はその区分、無ければ名前から決める。"""
    if qualification_name in CATEGORIES:
        return CATEGORIES[qualification_name]
    for word, category in _CATEGORY_WORDS:
        if word in qualification_name:
            return category
    return OTHER


def read_dates(csv_path):
    """有効期限の表を読む。

    形: 氏名,ファイル名,取得日,有効期限（日付は 2026-09-17 の形。空でよい）

    Returns:
        {(氏名の正規化, ファイル名): (取得日 or None, 有効期限 or None)}
    """
    dates = {}
    if not csv_path:
        return dates
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            person = normalize_person_name(row.get("氏名", ""))
            file_name = (row.get("ファイル名") or "").strip()
            if not person or not file_name:
                continue
            dates[(person, file_name)] = (
                _parse_date(row.get("取得日")), _parse_date(row.get("有効期限")),
            )
    return dates


def _parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.date.fromisoformat(value)


def collect_files(root):
    """フォルダを読み、(氏名, ファイルのパス, 資格名, 優先度) を返す。

    読み替え表に無いファイルは資格名を None にして返す（報告に出すため）。
    """
    found = []
    for person_dir in sorted(pathlib.Path(root).iterdir()):
        if not person_dir.is_dir():
            continue
        for path in sorted(person_dir.iterdir()):
            if path.suffix.lower() != ".pdf" or CHECKLIST_MARK in path.stem:
                continue
            mapped = FILE_TO_QUALIFICATION.get(path.stem)
            name, priority = mapped if mapped else (None, 0)
            found.append((person_dir.name, path, name, priority))
    return found


def import_certificates(root, company, Worker, WorkerQualification, *,
                        dates=None, apply=False):
    """資格証のPDFを保有資格に添付する。

    Returns:
        {
          "attached": [(氏名, 資格名, ファイル名, 有効期限)],  … 添付した（予定）
          "created":  [(氏名, 資格名)],        … 保有資格が無かったので作った（予定）
          "replaced": [(氏名, 資格名)],        … 既にあった添付を差し替えた（予定）
          "skipped_duplicate": [(氏名, 資格名, ファイル名)],  … 同じ資格の2枚目以降
          "unknown_file": [(氏名, ファイル名)],   … 読み替え表に無いファイル
          "unknown_worker": [氏名],             … 作業員が見つからない
        }
    """
    dates = dates or {}
    report = {
        "attached": [], "created": [], "replaced": [],
        "skipped_duplicate": [], "unknown_file": [], "unknown_worker": [],
    }

    workers = {
        normalize_person_name(worker.name): worker
        for worker in Worker._base_manager.filter(company=company)
    }

    # 同じ資格に複数のファイルがあるときは優先度の高いものだけ使う
    best = {}
    for person, path, name, priority in collect_files(root):
        if name is None:
            report["unknown_file"].append((person, path.name))
            continue
        key = (normalize_person_name(person), name)
        current = best.get(key)
        if current is None or priority > current[2]:
            if current is not None:
                report["skipped_duplicate"].append((person, name, current[1].name))
            best[key] = (person, path, priority)
        else:
            report["skipped_duplicate"].append((person, name, path.name))

    for (person_key, name), (person, path, _priority) in sorted(
        best.items(), key=lambda item: (item[0][0], item[0][1]),
    ):
        worker = workers.get(person_key)
        if worker is None:
            if person not in report["unknown_worker"]:
                report["unknown_worker"].append(person)
            continue

        qualification = (
            WorkerQualification._base_manager
            .filter(company=company, worker=worker, name=name)
            .order_by("pk")
            .first()
        )
        acquired, expiry = dates.get((person_key, path.name), (None, None))

        if qualification is None:
            report["created"].append((person, name))
            if apply:
                qualification = WorkerQualification._base_manager.create(
                    company=company, worker=worker, name=name,
                    category=category_for(name),
                )
        elif qualification.certificate_image:
            report["replaced"].append((person, name))

        report["attached"].append((person, name, path.name, expiry))
        if not apply:
            continue

        with open(path, "rb") as fh:
            qualification.certificate_image.save(path.name, File(fh), save=False)
        if acquired:
            qualification.acquired_date = acquired
        if expiry:
            qualification.expiry_date = expiry
        qualification.save()

    return report
