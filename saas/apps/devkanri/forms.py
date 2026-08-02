from django import forms

from apps.accounts.models import User
from apps.devkanri.models import DevComment, DevProject, DevTask


class DevProjectForm(forms.ModelForm):
    class Meta:
        model = DevProject
        fields = ["name", "description", "status", "assignee", "start_date", "due_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "due_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["assignee"].queryset = User.objects.filter(company=company)


class DevTaskForm(forms.ModelForm):
    class Meta:
        model = DevTask
        fields = [
            "title", "description", "status", "priority", "category",
            "assignee", "due_date", "estimate_hours", "actual_hours",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["assignee"].queryset = User.objects.filter(company=company)


class DevCommentForm(forms.ModelForm):
    class Meta:
        model = DevComment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "コメントを入力...",
            }),
        }
