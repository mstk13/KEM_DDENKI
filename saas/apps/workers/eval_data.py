"""評価アンケートデータの読み込み。

static/data/ の JSON から評価項目・質問を読み込み、
対象者の職種に応じたセクションを返す。
"""

import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "data"


def _load_json(filename):
    with open(_DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def get_eval_items():
    """eval_items.json を返す。"""
    return _load_json("eval_items.json")


def get_survey_data():
    """survey_questions.json を返す。"""
    return _load_json("survey_questions.json")


def get_sections_for_worker(worker):
    """対象者の職種に基づき、該当する評価セクションを返す。

    Returns: (items_for_worker, survey_items_for_worker, scale, overall)
    """
    eval_items = get_eval_items()
    survey = get_survey_data()

    job_name = str(worker.job_title) if worker.job_title else ""

    # 該当セクション判定
    applicable_sections = ["共通"]
    if job_name == "電工":
        applicable_sections.append("電工")
    elif job_name in ("事務", "developer"):
        applicable_sections.append("事務")

    # eval_items からフィルタ
    items = [i for i in eval_items if i["section"] in applicable_sections]

    # survey_questions からフィルタ
    survey_items = [i for i in survey["items"] if i["section"] in applicable_sections]

    return {
        "items": items,
        "survey_items": survey_items,
        "scale": survey["scale"],
        "overall": survey["overall"],
        "sections": applicable_sections,
    }
