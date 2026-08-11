from django import forms

from apps.bids.models import BidCompetitor, BidCost, BidProject, Qualification, ScrapeTarget, UnitPrice


class BidProjectForm(forms.ModelForm):
    class Meta:
        model = BidProject
        fields = [
            "title", "client", "region", "category",
            "deadline", "budget", "source_url", "status",
            "required_category", "required_grade", "required_issuer_type",
        ]
        widgets = {
            "deadline": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.DateInput):
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


class ScrapeTargetForm(forms.ModelForm):
    class Meta:
        model = ScrapeTarget
        fields = [
            "name", "keyword", "region", "prefecture",
            "category", "days_back", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
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
