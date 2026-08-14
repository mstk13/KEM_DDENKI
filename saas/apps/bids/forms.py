from django import forms

from apps.bids.models import (
    BidCompetitor, BidCost, BidProject, Qualification, ScrapeTarget, UnitPrice,
)


class BidProjectForm(forms.ModelForm):
    # summary は情報源の原文なので画面からは編集させない（詳細画面で表示のみ）
    class Meta:
        model = BidProject
        fields = [
            "title", "client", "agency_dept", "region", "location",
            "category", "bid_method", "electronic_bid", "design_no",
            "announced_on", "deadline", "opening_on",
            "budget", "source_url", "status", "notes",
        ]
        widgets = {
            "announced_on": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "deadline": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "opening_on": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.DateInput, forms.Textarea)):
                field.widget.attrs.setdefault("class", "form-control")


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
            "is_active", "scrape_interval_hours",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
