from django import forms

from apps.accounts.models import User
from apps.devkanri.models import DevComment, DevProject, DevTask


def _get_developer_users(company):
    """開発者（社員番号Gで始まる）＋管理者のユーザーを取得する。"""
    from apps.workers.models import Worker

    # 社員番号Gで始まるWorkerに紐づくUser
    developer_user_ids = (
        Worker.unscoped.filter(
            company=company,
            employee_code__startswith="G",
            user__isnull=False,
            is_active=True,
        ).values_list("user_id", flat=True)
    )
    # superuser + developer users
    return User.objects.filter(
        company=company,
    ).filter(
        models.Q(pk__in=developer_user_ids) | models.Q(is_superuser=True)
    )


# Django models.Q を使うためimport
from django.db import models


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
            self.fields["assignee"].queryset = _get_developer_users(company)


class DevTaskForm(forms.ModelForm):
    class Meta:
        model = DevTask
        fields = [
            "title", "description", "status", "priority", "category",
            "assignee", "due_date", "estimate_hours", "actual_hours",
            "github_issue_url", "github_pr_url",
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
            self.fields["assignee"].queryset = _get_developer_users(company)


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
