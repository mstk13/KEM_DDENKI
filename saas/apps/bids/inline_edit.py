"""画面の文字をタップしてその場で直す（ADR-0073）。

入札管理の画面（入札案件・入札参加資格・単価マスタ・案件取得）で、表示している値を
タップして直せるようにするための受け口。直せる項目はここで決めた分だけに限る。

- 直せるのは EDITABLE に書いたモデルと項目だけ。ほかは受け付けない
- 入力の形（文字・数値・日付・選択）はモデルの項目から決める
- 保存はモデルフォームを通すので、いつもの入力チェックがそのまま効く
- テナントは company で絞られたマネージャ（objects）で引くので、他社のデータは触れない
"""

from django import forms
from django.apps import apps

# 直せるモデルと項目。画面に出している順に並べる
EDITABLE = {
    "bids.BidProject": [
        "title", "client", "agency_dept", "location", "region", "category",
        "bid_method", "electronic_bid", "design_no", "budget", "status",
        "announced_on", "opening_on", "deadline", "source_url",
        "required_issuer_type", "required_category", "required_grade",
        "required_grades", "required_score",
        "summary", "work_outline", "requirements", "notes",
    ],
    "bids.Qualification": [
        "issuer", "category", "grade", "keisin_score", "total_score",
        "vendor_number", "valid_from", "valid_until", "renewed", "memo",
    ],
    "bids.ConstructionLicense": [
        "trade", "license_class", "grantor_type", "authority", "license_number",
        "valid_from", "valid_until", "renewal_deadline", "renewed", "memo",
    ],
    "bids.UnifiedQualification": [
        "agency", "goods_sales_grade", "goods_sales_score", "goods_sales_items",
        "services_grade", "services_score", "services_items",
        "purchase_grade", "purchase_score",
    ],
    "bids.BidCost": ["estimate_amount", "actual_cost", "memo"],
    "bids.BidCompetitor": ["competitor_name", "competitor_amount", "source", "memo"],
    "bids.UnitPrice": ["category", "item_name", "unit", "unit_price", "memo"],
    "bids.ScrapeTarget": [
        "name", "url", "region", "prefecture", "keyword", "koji_gyosyu",
        "days_back", "scrape_interval_hours", "is_active", "only_eligible",
    ],
}

# 空欄のときに画面へ出す文字
EMPTY_DISPLAY = "-"


class NotEditable(Exception):
    """許していないモデル・項目を指されたとき。"""


def get_model(model_label):
    if model_label not in EDITABLE:
        raise NotEditable(f"{model_label} はその場で直せません。")
    return apps.get_model(model_label)


def get_field(model_label, field_name):
    if field_name not in EDITABLE.get(model_label, ()):
        raise NotEditable(f"{model_label}.{field_name} はその場で直せません。")
    return get_model(model_label)._meta.get_field(field_name)


def input_type(field):
    """入力欄の種類。テンプレートの data-type と揃える。"""
    if getattr(field, "choices", None):
        return "select"
    internal = field.get_internal_type()
    if internal == "BooleanField":
        return "boolean"
    if internal == "DateField":
        return "date"
    if internal == "DateTimeField":
        return "datetime"
    if internal in ("IntegerField", "PositiveIntegerField", "PositiveSmallIntegerField",
                    "SmallIntegerField", "BigIntegerField", "DecimalField", "FloatField"):
        return "number"
    if internal == "TextField":
        return "textarea"
    return "text"


def display_value(obj, field):
    """画面に出す文字。空なら「-」。"""
    if getattr(field, "choices", None):
        return getattr(obj, f"get_{field.name}_display")() or EMPTY_DISPLAY
    value = getattr(obj, field.name)
    if value is None or value == "":
        return EMPTY_DISPLAY
    internal = field.get_internal_type()
    if internal == "BooleanField":
        return "はい" if value else "いいえ"
    if internal == "DateField":
        return value.strftime("%Y/%m/%d")
    if internal == "DateTimeField":
        from django.utils import timezone

        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return local.strftime("%Y/%m/%d %H:%M")
    if internal in ("DecimalField", "FloatField"):
        return f"{value:,.0f}"
    if internal in ("IntegerField", "PositiveIntegerField", "PositiveSmallIntegerField",
                    "SmallIntegerField", "BigIntegerField"):
        return f"{value:,}"
    return str(value)


def raw_value(obj, field):
    """入力欄に最初から入れる値。"""
    value = getattr(obj, field.name)
    if value is None:
        return ""
    internal = field.get_internal_type()
    if internal == "BooleanField":
        return "true" if value else "false"
    if internal == "DateField":
        return value.isoformat()
    if internal == "DateTimeField":
        from django.utils import timezone

        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return local.strftime("%Y-%m-%dT%H:%M")
    return str(value)


def choices_for(field):
    """選択肢。[(値, 表示)]。空欄を許す項目には空の選択肢も足す。"""
    choices = [(str(value), str(label)) for value, label in (field.choices or [])]
    if field.blank and not any(value == "" for value, _ in choices):
        choices.insert(0, ("", EMPTY_DISPLAY))
    return choices


def save_value(obj, field, value):
    """1項目だけを保存する。入力チェックはモデルフォームに任せる。

    Returns:
        (画面に出す文字, 入力欄に入れる値)

    Raises:
        django.core.exceptions.ValidationError 相当のエラーは forms.ValidationError で投げず、
        呼び出し側に文字列で返せるよう ValueError にして返す。
    """
    form_class = forms.modelform_factory(type(obj), fields=[field.name])
    form = form_class({field.name: value}, instance=obj)
    if not form.is_valid():
        raise ValueError("／".join(form.errors[field.name]))
    saved = form.save()
    # 入札案件の項目を直したら「人が直した」印を付け、公告の取り直しで書き換えない（ADR-0075）
    mark = getattr(saved, "mark_corrected", None)
    if mark is not None and form.changed_data and mark(form.changed_data):
        saved.save(update_fields=["corrected_fields"])
    return display_value(saved, field), raw_value(saved, field)
