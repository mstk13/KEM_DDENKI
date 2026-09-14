import re
import unicodedata
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.core.date_utils import add_years
from apps.workers.models import (
    HealthCheckup,
    JobTitle,
    Position,
    Worker,
    WorkerEvaluation,
    WorkerQualification,
)

# 社会保険（ADR-0059）。見て直せる人は現住所などと同じ
WORKER_INSURANCE_FIELDS = (
    "health_insurance",
    "pension_insurance",
    "employment_insurance",
    "employment_insurance_number_last4",
)
# 管理者・事務員・本人だけが見て直せる項目（ADR-0057・ADR-0059）。
# 見られない人のフォームからは欄ごと外すので、送られてきても保存しない。
WORKER_PRIVATE_FIELDS = (
    "postal_code",
    "address",
    "emergency_contact_name",
    "emergency_contact_relationship",
    "emergency_contact_postal_code",
    "emergency_contact_address",
    "emergency_contact_phone",
    *WORKER_INSURANCE_FIELDS,
    "blood_type",
)
HEALTH_VISION_FIELDS = (
    "vision_right_naked",
    "vision_left_naked",
    "vision_right_corrected",
    "vision_left_corrected",
)
HEALTH_BLOOD_PRESSURE_FIELDS = ("blood_pressure_high", "blood_pressure_low")
HEALTH_PRIVATE_FIELDS = HEALTH_VISION_FIELDS + HEALTH_BLOOD_PRESSURE_FIELDS


def split_fields(form, names):
    """フォームの欄を（names に無い欄, names にある欄）に分ける。

    テンプレートで区切って出すため。
    """
    names = set(names)
    return (
        [field for field in form if field.name not in names],
        [field for field in form if field.name in names],
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
    # 経験年数は数字で入れ、保存するときに「起算日」（今日からその年数を引いた日）にして持つ。
    # 表示は起算日からの満年数なので、年が経つと自動で増える（ADR-0057）。
    experience_years = forms.IntegerField(
        label="経験年数",
        required=False,
        min_value=0,
        max_value=70,
        help_text="この仕事の経験年数。入力した日から1年ごとに自動で1年ずつ増えます。",
    )

    class Meta:
        model = Worker
        fields = [
            "name", "name_kana", "job_title", "position",
            "phone", "hourly_cost", "birth_date", "hire_date", "experience_years",
            "is_active", "note", "discord_user_id",
            *WORKER_PRIVATE_FIELDS,
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "postal_code": forms.TextInput(
                attrs={"inputmode": "numeric", "autocomplete": "postal-code"},
            ),
            "emergency_contact_postal_code": forms.TextInput(attrs={"inputmode": "numeric"}),
            "emergency_contact_phone": forms.TextInput(attrs={"type": "tel"}),
            "employment_insurance_number_last4": forms.TextInput(
                attrs={"inputmode": "numeric", "autocomplete": "off", "placeholder": "例: 1234"},
            ),
        }

    def __init__(self, *args, company=None, can_view_private=False, **kwargs):
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
        self.can_view_private = can_view_private
        if not can_view_private:
            for name in WORKER_PRIVATE_FIELDS:
                self.fields.pop(name, None)
        self._initial_experience_years = self.instance.experience_years
        self.fields["experience_years"].initial = self._initial_experience_years

    def clean(self):
        cleaned = super().clean()
        if "employment_insurance" not in self.fields:
            return cleaned  # 見られない人のフォーム（社会保険の欄が無い）
        # 雇用保険に加入していれば、被保険者番号の下4桁が要る（ADR-0059）。全角の数字も受け付ける
        raw = self.data.get(self.add_prefix("employment_insurance_number_last4"), "")
        number = unicodedata.normalize("NFKC", raw).strip()
        if cleaned.get("employment_insurance") == Worker.EmploymentInsurance.ENROLLED:
            if re.fullmatch(r"[0-9]{4}", number):
                cleaned["employment_insurance_number_last4"] = number
                self.errors.pop("employment_insurance_number_last4", None)
            else:
                self.add_error(
                    "employment_insurance_number_last4",
                    "雇用保険に加入しているときは、被保険者番号の下4桁を数字4つで入れてください。",
                )
        else:
            # 加入していない人の番号は残さない
            self.errors.pop("employment_insurance_number_last4", None)
            cleaned["employment_insurance_number_last4"] = ""
        return cleaned

    def save(self, commit=True):
        worker = super().save(commit=False)
        years = self.cleaned_data.get("experience_years")
        if years is None:
            worker.experience_started_on = None
        elif years != self._initial_experience_years:
            # 年数を入れ直したときだけ起算日を引き直す（そのまま保存しても起算日がずれないように）
            worker.experience_started_on = add_years(timezone.localdate(), -years)
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
    VISION_MAX = Decimal("3")
    BLOOD_PRESSURE_HIGH_RANGE = (50, 300)
    BLOOD_PRESSURE_LOW_RANGE = (20, 200)

    class Meta:
        model = HealthCheckup
        fields = [
            "checkup_date", "result", "institution", "memo", "report_file",
            *HEALTH_PRIVATE_FIELDS,
        ]
        widgets = {
            "checkup_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            **{
                name: forms.NumberInput(
                    attrs={"step": "0.01", "min": "0", "max": "3", "inputmode": "decimal"},
                )
                for name in HEALTH_VISION_FIELDS
            },
            **{
                name: forms.NumberInput(attrs={"min": "0", "max": "300", "inputmode": "numeric"})
                for name in HEALTH_BLOOD_PRESSURE_FIELDS
            },
        }

    def __init__(self, *args, can_view_private=False, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        # 視力・血圧は管理者・事務員・本人だけ（ADR-0057）。
        # ほかの人には欄を出さず、送られても保存しない
        self.can_view_private = can_view_private
        if not can_view_private:
            for name in HEALTH_PRIVATE_FIELDS:
                self.fields.pop(name, None)

    def clean(self):
        cleaned = super().clean()
        for name in HEALTH_VISION_FIELDS:
            value = cleaned.get(name)
            if value is not None and not (0 <= value <= self.VISION_MAX):
                self.add_error(name, "視力は 0〜3.0 の数字で入れてください（例: 1.2）。")
        high = cleaned.get("blood_pressure_high")
        low = cleaned.get("blood_pressure_low")
        high_min, high_max = self.BLOOD_PRESSURE_HIGH_RANGE
        low_min, low_max = self.BLOOD_PRESSURE_LOW_RANGE
        if high is not None and not high_min <= high <= high_max:
            self.add_error(
                "blood_pressure_high",
                f"血圧（上）は {high_min}〜{high_max} の数字で入れてください。",
            )
        if low is not None and not low_min <= low <= low_max:
            self.add_error(
                "blood_pressure_low",
                f"血圧（下）は {low_min}〜{low_max} の数字で入れてください。",
            )
        if high is not None and low is not None and high <= low:
            self.add_error(
                "blood_pressure_low",
                "血圧（下）は、血圧（上）より小さい数字にしてください。",
            )
        return cleaned


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
