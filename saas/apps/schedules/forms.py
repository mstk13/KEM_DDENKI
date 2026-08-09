from django import forms

from apps.schedules.models import Assignment, Milestone, Phase
from apps.workers.models import Worker


class PhaseForm(forms.ModelForm):
    class Meta:
        model = Phase
        fields = ["name", "start_date", "end_date", "progress", "sort_order", "color", "memo"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ["name", "target_date", "completed", "memo"]
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            plain_widgets = (forms.Textarea, forms.DateInput, forms.CheckboxInput)
            if not isinstance(field.widget, plain_widgets):
                field.widget.attrs.setdefault("class", "form-control")


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["worker", "start_date", "end_date", "memo"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["worker"].queryset = Worker.objects.filter(company=company)
