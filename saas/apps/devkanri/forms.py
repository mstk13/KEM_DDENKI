from django import forms

from apps.accounts.models import User
from apps.accounts.views import _get_or_create_user
from apps.devkanri.models import DevComment, DevProject, DevTask, Meyasubako
from apps.workers.models import Worker


def _ensure_users_for_dev_workers(company):
    """Gプレフィックス（Developer）の作業員に対応する User を確保して返す。"""
    for worker in Worker.unscoped.filter(
        company=company, is_active=True, employee_code__startswith="G", user__isnull=True,
    ):
        _get_or_create_user(worker)
    # Gプレフィックスの作業員に紐づくUserのみ返す
    return User.objects.filter(
        company=company,
        worker_profile__employee_code__startswith="G",
        worker_profile__is_active=True,
    )


class DevProjectForm(forms.ModelForm):
    class Meta:
        model = DevProject
        fields = ["name", "description", "status", "assignee", "start_date", "due_date", "discord_webhook_url"]
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
            self.fields["assignee"].queryset = _ensure_users_for_dev_workers(company)


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
            self.fields["assignee"].queryset = _ensure_users_for_dev_workers(company)


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


class MeyasubakoForm(forms.ModelForm):
    reporter_worker = forms.ModelChoiceField(
        queryset=Worker.objects.none(),
        label="報告者",
        empty_label="-- 選択してください --",
    )

    class Meta:
        model = Meyasubako
        fields = ["reporter_worker", "kind", "module", "title", "problem", "wish", "urgency", "screenshot"]
        widgets = {
            "problem": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "何が起きましたか？ 何に困っていますか？"}),
            "wish": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "どうなると嬉しいですか？（任意）"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["reporter_worker"].queryset = Worker.objects.filter(
                company=company,
            ).order_by("name")
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.FileInput)):
                field.widget.attrs.setdefault("class", "form-control")
