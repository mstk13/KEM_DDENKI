"""評価項目とアンケート設問を、書き出して読み込む（ADR-0102）。

評価項目（`EvalItem`）と設問（`SurveyQuestion`）は、画面から直せるデータである。
開発環境で直しても、本番の DB は別物なので反映されない
（プロダクトオーナーの申告、2026-09-19）。

そこで、片方の環境で書き出したファイルを、もう片方で読み込めるようにする。

- 書き出しは JSON。中身は人が読んで確かめられる形にする
- 読み込みは**足すか直すだけ**。書き出し側に無い項目を勝手に消さない
  （消すのは取り返しがつかないので、画面の削除から人が行う）
- 同じ項目かどうかは「セクション＋項目番号」で見る。設問は「項目＋質問番号」で見る
- 会社は読み込む側のものを使う。ファイルに入っている会社は見ない
"""

import json

FORMAT = "kem-eval-items"
VERSION = 1

ITEM_FIELDS = (
    "section", "num", "name", "description", "max_score",
    "choice_group", "sort_order", "anchor_5", "anchor_3", "anchor_1", "free_text",
)
QUESTION_FIELDS = ("qnum", "text", "sort_order")


def export_items(company, EvalItem):
    """評価項目と設問を、書き出す形の辞書にする。"""
    items = []
    # unscoped: 会社を明示して絞る。コマンドからも呼ぶため
    rows = (
        EvalItem._base_manager.filter(company=company)
        .prefetch_related("questions")
        .order_by("section", "sort_order", "num")
    )
    for item in rows:
        data = {field: getattr(item, field) for field in ITEM_FIELDS}
        data["questions"] = [
            {field: getattr(question, field) for field in QUESTION_FIELDS}
            for question in item.questions.all().order_by("sort_order", "qnum")
        ]
        items.append(data)
    return {"format": FORMAT, "version": VERSION, "items": items}


def export_json(company, EvalItem) -> str:
    return json.dumps(export_items(company, EvalItem), ensure_ascii=False, indent=2)


class BadFile(ValueError):
    """読み込めないファイル。"""


def load_payload(raw):
    """書き出したファイルを読む。形が違えば BadFile。"""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise BadFile("ファイルを読めませんでした。書き出したJSONを選んでください。") from error

    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise BadFile("評価項目の書き出しファイルではありません。")
    items = payload.get("items")
    if not isinstance(items, list):
        raise BadFile("評価項目が入っていません。")
    return items


def import_items(company, EvalItem, SurveyQuestion, items, *, apply=True):
    """読み込んだ評価項目を、足すか直す。消しはしない。

    Returns:
        {
          "created": [(セクション, 項目番号, 項目名)],
          "updated": [(セクション, 項目番号, 直した項目の名前)],
          "questions_created": 件数,
          "questions_updated": 件数,
          "unchanged": 件数,
        }
    """
    report = {
        "created": [], "updated": [],
        "questions_created": 0, "questions_updated": 0, "unchanged": 0,
    }

    for data in items:
        section = str(data.get("section", "")).strip()
        num = data.get("num")
        if not section or num is None:
            continue

        values = {
            field: data.get(field)
            for field in ITEM_FIELDS
            if field not in ("section", "num") and data.get(field) is not None
        }
        item = EvalItem._base_manager.filter(
            company=company, section=section, num=num,
        ).first()

        if item is None:
            report["created"].append((section, num, values.get("name", "")))
            if apply:
                item = EvalItem._base_manager.create(
                    company=company, section=section, num=num, **values,
                )
        else:
            changed = [
                field for field, value in values.items()
                if getattr(item, field) != value
            ]
            if changed:
                report["updated"].append((section, num, values.get("name", "")))
                if apply:
                    for field in changed:
                        setattr(item, field, values[field])
                    item.save(update_fields=[*changed, "updated_at"])
            else:
                report["unchanged"] += 1

        if item is None:
            # 確認だけのときは、まだ作っていないので設問は数えるだけにする
            report["questions_created"] += len(data.get("questions") or [])
            continue

        _import_questions(
            company, SurveyQuestion, item, data.get("questions") or [],
            report=report, apply=apply,
        )

    return report


def _import_questions(company, SurveyQuestion, item, questions, *, report, apply):
    for data in questions:
        qnum = str(data.get("qnum", "")).strip()
        if not qnum:
            continue
        values = {
            field: data.get(field)
            for field in QUESTION_FIELDS
            if field != "qnum" and data.get(field) is not None
        }
        question = SurveyQuestion._base_manager.filter(
            company=company, item=item, qnum=qnum,
        ).first()

        if question is None:
            report["questions_created"] += 1
            if apply:
                SurveyQuestion._base_manager.create(
                    company=company, item=item, qnum=qnum, **values,
                )
            continue

        changed = [
            field for field, value in values.items()
            if getattr(question, field) != value
        ]
        if not changed:
            continue
        report["questions_updated"] += 1
        if apply:
            for field in changed:
                setattr(question, field, values[field])
            question.save(update_fields=[*changed, "updated_at"])
