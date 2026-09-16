import datetime

from django import forms
from django.utils import timezone

from apps.bids.models import (
    BidCompetitor,
    BidCost,
    BidProject,
    ConstructionLicense,
    Qualification,
    ScrapeTarget,
    UnifiedQualification,
    UnitPrice,
)


class BidProjectForm(forms.ModelForm):
    # summary は情報源の原文なので画面からは編集させない（詳細画面で表示のみ）
    class Meta:
        model = BidProject
        fields = [
            "title", "client", "agency_dept", "region", "location",
            "category", "bid_method", "electronic_bid", "design_no",
            "announced_on", "deadline", "opening_on",
            "budget", "source_url", "status",
            "required_category", "required_grade", "required_grades",
            "required_score", "required_issuer_type",
            "work_outline", "requirements", "notes",
        ]
        widgets = {
            "announced_on": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "opening_on": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "work_outline": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "requirements": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.DateInput, forms.Textarea)):
                field.widget.attrs.setdefault("class", "form-control")


# 入札期限は日付だけでなく時刻も持つ（ADR-0073）。
# <input type="date"> のままだと、公告から読んだ時刻（17時など）が編集のたびに消える。
# DateTimeLocalField はこのファイルの下のほうで定義しているので、最後に差し替える。
def _use_datetime_local_for_deadline():
    BidProjectForm.base_fields["deadline"] = DateTimeLocalField(label="入札期限")


class BidCostForm(forms.ModelForm):
    class Meta:
        model = BidCost
        fields = ["estimate_amount", "actual_cost", "memo"]
        widgets = {
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class BidCompetitorForm(forms.ModelForm):
    class Meta:
        model = BidCompetitor
        fields = ["competitor_name", "competitor_amount", "source", "memo"]
        widgets = {
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class QualificationForm(forms.ModelForm):
    class Meta:
        model = Qualification
        fields = [
            "issuer", "category", "grade", "keisin_score", "total_score",
            "vendor_number", "valid_from", "valid_until",
            "application_type", "application_method", "renewed", "memo",
        ]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "valid_until": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            plain_widgets = (forms.Textarea, forms.DateInput, forms.CheckboxInput)
            if not isinstance(field.widget, plain_widgets):
                field.widget.attrs.setdefault("class", "form-control")


class ConstructionLicenseForm(forms.ModelForm):
    """自社の建設業許可（ADR-0064）。"""

    class Meta:
        model = ConstructionLicense
        fields = [
            "trade", "license_class", "grantor_type", "authority", "license_number",
            "valid_from", "valid_until", "renewal_deadline", "renewed", "memo",
        ]
        widgets = {
            "valid_from": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d",
            ),
            "valid_until": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d",
            ),
            "renewal_deadline": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d",
            ),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            plain_widgets = (forms.Textarea, forms.DateInput, forms.CheckboxInput)
            if not isinstance(field.widget, plain_widgets):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        valid_from = cleaned.get("valid_from")
        valid_until = cleaned.get("valid_until")
        deadline = cleaned.get("renewal_deadline")
        if valid_from and valid_until and valid_until < valid_from:
            self.add_error("valid_until", "有効期間の終わりが始まりより前になっています。")
        if deadline and valid_until and deadline > valid_until:
            self.add_error(
                "renewal_deadline", "更新書類の提出期限が有効期間の終わりより後になっています。",
            )
        return cleaned


class UnifiedQualificationForm(forms.ModelForm):
    class Meta:
        model = UnifiedQualification
        fields = [
            "sort_order", "agency",
            "goods_sales_grade", "goods_sales_score", "goods_sales_items",
            "services_grade", "services_score", "services_items",
            "purchase_grade", "purchase_score",
        ]
        widgets = {
            "goods_sales_items": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "services_items": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class UnitPriceForm(forms.ModelForm):
    class Meta:
        model = UnitPrice
        fields = ["category", "item_name", "unit", "unit_price", "memo"]
        widgets = {
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class ScrapeTargetForm(forms.ModelForm):
    class Meta:
        model = ScrapeTarget
        fields = [
            "name", "url", "site_key",
            "keyword", "region", "prefecture", "koji_kbn", "koji_gyosyu",
            "days_back", "category_filter",
            "is_active", "only_eligible", "scrape_interval_hours",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # site_key をドロップダウン＋手入力可能にする
        choices = [("", "（空欄 = i-ppi.jp）")] + list(ScrapeTarget.SITE_KEY_CHOICES)
        self.fields["site_key"].widget = forms.Select(choices=choices)
        self.fields["site_key"].required = False
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")


# ---------------------------------------------------------------------------
# 公告の読み取りを直す（ADR-0073）
#
# 詳細画面の欄ごとに「直す」で開く小さなフォーム。直した項目には「人が直した」印を付け、
# 公告を取り直しても書き換えないようにする（BidProject.corrected_fields）。
# ---------------------------------------------------------------------------

# <input type="datetime-local"> が送ってくる形。日付だけの入力も受ける
DATETIME_LOCAL_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d")


class DateTimeLocalField(forms.DateTimeField):
    """時刻まで入れられる日時の欄。公告から読んだ時刻（17時など）を落とさない。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("input_formats", DATETIME_LOCAL_FORMATS)
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
        )
        super().__init__(**kwargs)


def parse_schedule_datetime(value):
    """別表の "2026-09-10T12:00" を欄の初期値にする。読めなければ None。"""
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def schedule_datetime_text(value) -> str:
    """欄の日時を別表と同じ "YYYY-MM-DDTHH:MM" の形にする。"""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%Y-%m-%dT%H:%M")


class BidCorrectionForm(forms.ModelForm):
    """直した項目に「人が直した」印を付けて保存する。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def save(self, commit=True):
        project = super().save(commit=False)
        project.mark_corrected(self.changed_data)
        if commit:
            project.save(
                update_fields=[*self.changed_data, "corrected_fields", "updated_at"],
            )
        return project


class BidOutlineForm(BidCorrectionForm):
    class Meta:
        model = BidProject
        fields = ["work_outline"]
        widgets = {"work_outline": forms.Textarea(attrs={"rows": 10})}


class BidRequirementsForm(BidCorrectionForm):
    class Meta:
        model = BidProject
        fields = ["requirements"]
        widgets = {"requirements": forms.Textarea(attrs={"rows": 10})}


class BidQualificationForm(BidCorrectionForm):
    class Meta:
        model = BidProject
        fields = [
            "required_category", "required_grade", "required_grades",
            "required_score", "required_issuer_type",
        ]


class BidDatesForm(BidCorrectionForm):
    deadline = DateTimeLocalField(label="入札期限")

    class Meta:
        model = BidProject
        fields = ["announced_on", "deadline", "opening_on"]
        widgets = {
            "announced_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "opening_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }


class BidScheduleForm(forms.Form):
    """別表から読んだ重要日程（項目名・日時・補足）を直す。

    項目名を空にした行は消える。末尾に空の行があるので、行の追加もできる。
    """

    MAX_ROWS = 20
    EXTRA_ROWS = 2

    def __init__(self, *args, project, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        items = list(project.bid_schedule or [])
        self.row_count = min(len(items) + self.EXTRA_ROWS, self.MAX_ROWS)
        for index in range(self.row_count):
            item = items[index] if index < len(items) else {}
            self.fields[f"label_{index}"] = forms.CharField(
                label="項目名", max_length=100, required=False,
                initial=item.get("label", ""),
                widget=forms.TextInput(attrs={"class": "form-control"}),
            )
            self.fields[f"datetime_{index}"] = DateTimeLocalField(
                label="日時", initial=parse_schedule_datetime(item.get("datetime")),
            )
            self.fields[f"detail_{index}"] = forms.CharField(
                label="補足", max_length=200, required=False,
                initial=item.get("detail", ""),
                widget=forms.TextInput(attrs={"class": "form-control"}),
            )

    def rows(self):
        """画面に並べる行（項目名・日時・補足の欄）。"""
        for index in range(self.row_count):
            yield {
                "label": self[f"label_{index}"],
                "datetime": self[f"datetime_{index}"],
                "detail": self[f"detail_{index}"],
            }

    def clean(self):
        cleaned = super().clean()
        for index in range(self.row_count):
            label = (cleaned.get(f"label_{index}") or "").strip()
            when = cleaned.get(f"datetime_{index}")
            if when and not label:
                self.add_error(f"label_{index}", "項目名を入れてください")
        return cleaned

    def save(self):
        items = []
        for index in range(self.row_count):
            label = (self.cleaned_data.get(f"label_{index}") or "").strip()
            if not label:
                continue
            item = {"label": label}
            when = self.cleaned_data.get(f"datetime_{index}")
            if when:
                item["datetime"] = schedule_datetime_text(when)
            detail = (self.cleaned_data.get(f"detail_{index}") or "").strip()
            if detail:
                item["detail"] = detail
            items.append(item)
        self.project.bid_schedule = items
        self.project.mark_corrected(["bid_schedule"])
        self.project.save(
            update_fields=["bid_schedule", "corrected_fields", "updated_at"],
        )
        return self.project


_use_datetime_local_for_deadline()
