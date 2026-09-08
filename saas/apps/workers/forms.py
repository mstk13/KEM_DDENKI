from django import forms

from apps.workers.models import (
    HealthCheckup,
    JobTitle,
    Position,
    Worker,
    WorkerEvaluation,
    WorkerQualification,
)


def _get_employee_code_prefix(job_title_name, position_name):
    """職種・役職から社員番号のプレフィックスを決定。"""
    pos = position_name or ""
    job = job_title_name or ""

    if pos == "社長":
        return "Y"
    if pos == "役員":
        return "S"
    if pos == "Developer":
        return "G"
    if pos == "アルバイト":
        return "A"
    if pos == "パート":
        return "P"
    if pos == "試用期間":
        return "T"
    if job == "電工" and pos in ("シニア", "ジュニア"):
        return "E"
    # 電工 or 事務の正社員はE
    if job in ("電工", "事務") and pos == "正社員":
        return "E"
    if job == "電工":
        return "E"
    return "W"


def _next_employee_code(prefix, company):
    """指定プレフィックスの次の連番を生成（例: E007）。"""
    existing = Worker.unscoped.filter(
        company=company,
        employee_code__startswith=prefix,
    ).values_list("employee_code", flat=True)

    max_num = 0
    for code in existing:
        try:
            num = int(code[len(prefix):])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"{prefix}{max_num + 1:03d}"


class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = [
            "name", "name_kana", "job_title", "position",
            "phone", "hourly_cost", "hire_date", "is_active", "note", "discord_user_id",
        ]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        self._company = company
        super().__init__(*args, **kwargs)
        self.fields["job_title"].required = True
        self.fields["position"].required = True
        self.fields["hourly_cost"].required = False
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["job_title"].queryset = JobTitle.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["position"].queryset = Position.unscoped.filter(
                company=company, is_active=True,
            )

    def save(self, commit=True):
        worker = super().save(commit=False)
        # 新規作成時 or 職種/役職が変わった場合に社員番号を自動割当
        job_name = worker.job_title.name if worker.job_title else ""
        pos_name = worker.position.name if worker.position else ""
        prefix = _get_employee_code_prefix(job_name, pos_name)

        should_assign = (
            not worker.employee_code
            or not worker.employee_code.startswith(prefix)
        )
        if should_assign and self._company:
            worker.employee_code = _next_employee_code(prefix, self._company)

        if commit:
            worker.save()
        return worker


APP_PERMISSION_CHOICES = [
    ("sites", "現場管理"),
    ("reports", "日報管理"),
    ("schedules", "工期管理"),
    ("costs", "原価・予実"),
    ("materials", "材料・発注"),
    ("workers", "作業員管理"),
    ("evaluations", "人材評価"),
    ("hr_evaluation", "人事評価"),
    ("bids", "入札管理"),
    ("devkanri", "開発管理"),
    ("masters", "マスタ管理"),
]


class AppPermissionForm(forms.Form):
    """作業員ごとのアプリ権限チェックボックス。"""

    apps = forms.MultipleChoiceField(
        choices=APP_PERMISSION_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="利用可能アプリ",
    )


class WorkerQualificationForm(forms.ModelForm):
    class Meta:
        model = WorkerQualification
        fields = ["name", "category", "acquired_date", "expiry_date", "certificate_image", "note"]
        widgets = {
            "acquired_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "expiry_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class HealthCheckupForm(forms.ModelForm):
    class Meta:
        model = HealthCheckup
        fields = ["checkup_date", "result", "institution", "memo", "report_file"]
        widgets = {
            "checkup_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class EvaluationForm(forms.ModelForm):
    class Meta:
        model = WorkerEvaluation
        fields = ["worker", "period", "score", "comment"]
        widgets = {
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        help_texts = {
            "period": "例: 2026-Q2, 2026年上期",
            "score": "1〜5 の整数",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["worker"].queryset = Worker.unscoped.filter(
                company=company, is_active=True,
            )
