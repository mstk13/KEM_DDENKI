"""安全書類の入力フォーム（ADR-0061）。"""

import base64
import binascii

from django import forms

from apps.safety.formats import QUESTIONS, RISK_LEVELS, RISK_ROWS, SC5_ITEMS, SC5_ROWS
from apps.safety.models import SIGNATURE_MAX_LENGTH, EntryConfirmation, KyParticipant, KySheet
from apps.workers.models import Worker

_PNG_PREFIX = "data:image/png;base64,"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def clean_signature(value, *, required):
    """画面で書いたサイン（PNG の data URL）を確かめる。

    PNG でない・大きすぎるものは受け付けない。
    """
    value = (value or "").strip()
    if not value:
        if required:
            raise forms.ValidationError("枠の中にサインを書いてください。")
        return ""
    unreadable = forms.ValidationError("サインを読み取れませんでした。書き直してください。")
    if not value.startswith(_PNG_PREFIX) or len(value) > SIGNATURE_MAX_LENGTH:
        raise unreadable
    try:
        raw = base64.b64decode(value[len(_PNG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise unreadable from exc
    if not raw.startswith(_PNG_MAGIC):
        raise unreadable
    return value


class SignatureField(forms.CharField):
    """サインを書く欄。

    画面の canvas に書いた内容を hidden の入力で受け取る（static/js/signature-pad.js）。
    """

    widget = forms.HiddenInput

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label", "サイン")
        kwargs.setdefault("required", True)
        super().__init__(*args, **kwargs)

    def clean(self, value):
        return clean_signature(value, required=self.required)


def _yes_no_field(label, yes="はい", no="いいえ"):
    """はい・いいえで答える質問。答えていなければ None。"""
    return forms.TypedChoiceField(
        label=label,
        required=False,
        choices=[("True", yes), ("False", no)],
        coerce=lambda value: value == "True",
        empty_value=None,
        widget=forms.RadioSelect,
    )


def _add_form_control(form):
    for field in form.fields.values():
        if isinstance(field.widget, (forms.RadioSelect, forms.CheckboxInput, forms.HiddenInput)):
            continue
        field.widget.attrs.setdefault("class", "form-control")


# ---------------------------------------------------------------------------
# 安全作業確認書
# ---------------------------------------------------------------------------


class EntryConfirmationForm(forms.ModelForm):
    shock_education = _yes_no_field(
        "「感電災害事故防止教育・指導パトロール」で教育・指導を受けましたか？"
    )
    has_illness = _yes_no_field(
        "現在病気・身体の具合の悪い所はありますか？", yes="ある", no="ない"
    )
    received_employment_document = _yes_no_field(
        QUESTIONS["received_employment_document"],
        yes="受けた",
        no="受けてない",
    )
    received_safety_education = _yes_no_field(
        QUESTIONS["received_safety_education"],
        yes="受けた",
        no="受けてない",
    )
    special_accident_insurance = _yes_no_field(
        QUESTIONS["special_accident_insurance"],
        yes="はい（保険証写し添付）",
    )
    has_retirement_system = _yes_no_field(
        QUESTIONS["has_retirement_system"],
        yes="はい（⑦は答えなくてよい）",
    )
    has_kentaikyo_book = _yes_no_field(QUESTIONS["has_kentaikyo_book"])
    blood_type = forms.ChoiceField(
        label="血液型",
        required=False,
        choices=[("", "未入力"), *Worker.BloodType.choices],
    )
    signature = SignatureField(label="氏名（自筆サイン）")

    class Meta:
        model = EntryConfirmation
        fields = [
            "entry_date",
            "name_kana",
            "birth_date",
            "foreman_name",
            "transport",
            "partner_company_1",
            "partner_company_2",
            "partner_company_n_tier",
            "partner_company_n",
            "address",
            "phone",
            "emergency_contact_name",
            "emergency_contact_address",
            "emergency_contact_phone",
            "experience_years",
            "experience_months",
            "blood_type",
            "blood_pressure_high",
            "blood_pressure_low",
            "vision_right",
            "vision_left",
            "shock_education",
            "has_illness",
            "illness_detail",
            "business_type",
            "received_employment_document",
            "received_safety_education",
            "paying_company",
            "special_accident_insurance",
            "has_retirement_system",
            "has_kentaikyo_book",
            "signature",
        ]
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date"}),
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "phone": forms.TextInput(attrs={"type": "tel"}),
            "emergency_contact_phone": forms.TextInput(attrs={"type": "tel"}),
            "business_type": forms.RadioSelect,
        }
        labels = {
            "business_type": QUESTIONS["business_type"],
            "paying_company": QUESTIONS["paying_company"],
            "illness_detail": "具合の悪い所（「ある」のとき）",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 選択肢の「---------」は出さない（答えていない＝空のまま）
        self.fields["business_type"].choices = EntryConfirmation.BusinessType.choices
        self.fields["business_type"].required = False
        _add_form_control(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("has_illness") and not (cleaned.get("illness_detail") or "").strip():
            self.add_error("illness_detail", "具合の悪い所を書いてください。")
        return cleaned


# ---------------------------------------------------------------------------
# KY用紙
# ---------------------------------------------------------------------------


class KySheetForm(forms.ModelForm):
    """KY用紙の上半分（作業責任者が書くところ）。

    危険の行と SC-5 の確認は、行ごとの欄にして JSON にまとめる。
    """

    class Meta:
        model = KySheet
        fields = [
            "crew_name",
            "planned_headcount",
            "work_start",
            "work_end",
            "leader_name",
            "work_content",
            "safety_instructions",
            "extra_check_7",
            "extra_check_8",
            "sc5_extra_5",
            "sc5_extra_6",
            "remarks",
        ]
        widgets = {
            "work_start": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "work_end": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "work_content": forms.Textarea(attrs={"rows": 4}),
            "safety_instructions": forms.Textarea(attrs={"rows": 4}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        risks = (self.instance.risks if self.instance.pk else self.initial.get("risks")) or []
        checks = (self.instance.sc5_checks if self.instance.pk else []) or []
        for i in range(RISK_ROWS):
            row = risks[i] if i < len(risks) else {}
            self.fields[f"risk_hazard_{i}"] = forms.CharField(
                label=f"予想される危険 {i + 1}",
                max_length=100,
                required=False,
                initial=row.get("hazard", ""),
            )
            self.fields[f"risk_level_{i}"] = forms.ChoiceField(
                label="危険度",
                required=False,
                choices=[("", "－"), *[(level, level) for level in RISK_LEVELS]],
                initial=row.get("level", ""),
            )
            self.fields[f"risk_measure_{i}"] = forms.CharField(
                label="低減措置",
                max_length=200,
                required=False,
                initial=row.get("measure", ""),
            )
            self.fields[f"risk_checked_{i}"] = forms.BooleanField(
                label="作業中確認",
                required=False,
                initial=bool(row.get("checked")),
            )
        for i in range(SC5_ROWS):
            self.fields[f"sc5_check_{i}"] = forms.BooleanField(
                label="朝礼時確認",
                required=False,
                initial=bool(checks[i]) if i < len(checks) else False,
            )
        _add_form_control(self)

    def risk_rows(self):
        return [
            {
                "hazard": self[f"risk_hazard_{i}"],
                "level": self[f"risk_level_{i}"],
                "measure": self[f"risk_measure_{i}"],
                "checked": self[f"risk_checked_{i}"],
            }
            for i in range(RISK_ROWS)
        ]

    def sc5_rows(self):
        """SC-5 の行。1〜4 は様式の文言、5・6 は書き足す欄。"""
        rows = []
        for i in range(SC5_ROWS):
            extra = self[f"sc5_extra_{i + 1}"] if i >= len(SC5_ITEMS) else None
            rows.append(
                {
                    "number": i + 1,
                    "text": SC5_ITEMS[i] if i < len(SC5_ITEMS) else "",
                    "extra": extra,
                    "check": self[f"sc5_check_{i}"],
                }
            )
        return rows

    def save(self, commit=True):
        sheet = super().save(commit=False)
        data = self.cleaned_data
        sheet.risks = [
            {
                "hazard": (data.get(f"risk_hazard_{i}") or "").strip(),
                "level": data.get(f"risk_level_{i}") or "",
                "measure": (data.get(f"risk_measure_{i}") or "").strip(),
                "checked": bool(data.get(f"risk_checked_{i}")),
            }
            for i in range(RISK_ROWS)
        ]
        sheet.sc5_checks = [bool(data.get(f"sc5_check_{i}")) for i in range(SC5_ROWS)]
        if commit:
            sheet.save()
        return sheet


class KyParticipantForm(forms.Form):
    """KY用紙の自分の行。1台のスマホを回して書けるよう、作業員を選べるようにする。"""

    worker = forms.ModelChoiceField(label="作業員", queryset=Worker.objects.none())
    health = forms.ChoiceField(
        label="健康状態",
        choices=KyParticipant.Health.choices,
        initial=KyParticipant.Health.GOOD,
        widget=forms.RadioSelect,
    )
    health_note = forms.CharField(label="不調のときの症状", max_length=200, required=False)
    tester = forms.ChoiceField(
        label="検電器",
        choices=KyParticipant.Tester.choices,
        widget=forms.RadioSelect,
    )
    signature = SignatureField(label="氏名（自筆サイン）")

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        # unscoped: 候補は現場の会社の在籍者だけ。テナントの文脈に頼らず会社で明示的に絞る
        self.fields["worker"].queryset = (
            Worker.unscoped.filter(company=company, is_active=True).order_by(
                "employee_code", "name"
            )
            if company is not None
            else Worker.objects.none()
        )
        _add_form_control(self)

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("health") == KyParticipant.Health.POOR
            and not (cleaned.get("health_note") or "").strip()
        ):
            self.add_error("health_note", "不調のときは、症状を書いてください。")
        return cleaned


class KySignoffForm(forms.Form):
    """指導事項・確認・作業完了報告・現場巡視指導記録のサイン（文を書く欄があるものは文も）。"""

    text = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    signature = SignatureField()

    def __init__(self, *args, text_label=None, signature_label="サイン", **kwargs):
        super().__init__(*args, **kwargs)
        if text_label:
            self.fields["text"].label = text_label
        else:
            del self.fields["text"]
        self.fields["signature"].label = signature_label
        _add_form_control(self)
