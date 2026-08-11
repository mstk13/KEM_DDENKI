"""評価テンプレートデータの取得。

1. テナントの EvaluationTemplate があればそれを使う
2. なければ static/data/ の JSON をフォールバックとして使う

テンプレートがテナントごとにカスタマイズ可能なため、
フォールバックは初期セットアップ or テンプレート未作成時のみ使われる。
"""

import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "data"

# 設問1問ごとの回答は「はい/いいえ」の2択。
# 項目全体の評価と総合評点は従来どおり scale（5段階）を使うため、
# こちらはテナントのテンプレートに関わらず固定とする。
QUESTION_SCALE = [
    {"value": 1, "label": "はい"},
    {"value": 0, "label": "いいえ"},
]


def _load_json(filename):
    with open(_DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _fallback_eval_items():
    return _load_json("eval_items.json")


def _fallback_survey():
    return _load_json("survey_questions.json")


def get_template_for_company(company):
    """テナントの有効な EvaluationTemplate を返す。なければ None。"""
    from apps.workers.models import EvaluationTemplate

    return (
        EvaluationTemplate.unscoped.filter(company=company, is_active=True)
        .order_by("-created_at")
        .first()
    )


def get_sections_for_worker(worker, company=None):
    """対象者の職種に基づき、該当する評価データを返す。

    テナントにテンプレートがあればそれを使い、なければ JSON フォールバック。
    """
    company = company or worker.company
    job_name = str(worker.job_title) if worker.job_title else ""
    return get_sections_for_role(job_name, company)


def get_available_roles(company):
    """評価シートを作成できる職種名の一覧を返す（共通を除く）。"""
    template = get_template_for_company(company)
    items = template.survey_items if template else _fallback_survey()["items"]
    sections = {i.get("section") for i in items if i.get("section") != "共通"}
    # 表示順は固定（一覧に無いものは末尾へ）
    order = ["電工", "事務", "役員", "社長"]
    return sorted(sections, key=lambda s: (order.index(s) if s in order else 99, s))


def get_sections_for_role(job_name, company):
    """職種名に基づき、該当する評価データを返す。

    特定の作業員に紐づかない「役職別の白紙シート」でも使えるよう、
    Worker ではなく職種名を受け取る。
    """
    template = get_template_for_company(company)

    if template:
        eval_items = template.sections
        survey_data_items = template.survey_items
        scale = template.scale
        overall = template.overall
    else:
        eval_items = _fallback_eval_items()
        survey = _fallback_survey()
        survey_data_items = survey["items"]
        scale = survey["scale"]
        overall = survey["overall"]

    # 該当セクション判定
    applicable_sections = ["共通"]
    if job_name == "電工":
        applicable_sections.append("電工")
    elif job_name in ("事務", "developer"):
        applicable_sections.append("事務")
    # テンプレートに存在するセクション名から自動判定（将来の業種拡張対応）
    if template:
        all_sections = {i.get("section") for i in eval_items}
        # 共通以外で job_name と一致するセクションがあれば追加
        if job_name in all_sections and job_name not in applicable_sections:
            applicable_sections.append(job_name)

    items = [i for i in eval_items if i.get("section") in applicable_sections]
    survey_items = [i for i in survey_data_items if i.get("section") in applicable_sections]

    return {
        "items": items,
        "survey_items": survey_items,
        "scale": scale,
        "question_scale": QUESTION_SCALE,
        "overall": overall,
        "sections": applicable_sections,
        "template": template,
    }
