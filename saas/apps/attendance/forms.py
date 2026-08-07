from django import forms
from django.forms import inlineformset_factory

from apps.attendance.models import AttendEntry, AttendReport, AttendSettings


class AttendReportForm(forms.ModelForm):
    class Meta:
        model = AttendReport
        fields = [
            "report_date", "site_name", "work_content",
            "note", "status", "source_text",
        ]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "work_content": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "source_text": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")


class AttendEntryForm(forms.ModelForm):
    class Meta:
        model = AttendEntry
        fields = [
            "worker", "employee_name", "start_time", "end_time",
            "break_minutes", "note",
        ]
        widgets = {
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


AttendEntryFormSet = inlineformset_factory(
    AttendReport,
    AttendEntry,
    form=AttendEntryForm,
    extra=3,
    can_delete=True,
)


class AttendSettingsForm(forms.Form):
    """キーバリュー設定を通常フォームで表示する。"""

    standard_start = forms.CharField(
        label="所定開始時刻", max_length=10, initial="08:00",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "08:00"}),
    )
    standard_end = forms.CharField(
        label="所定終了時刻", max_length=10, initial="17:00",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "17:00"}),
    )
    early_boundary = forms.CharField(
        label="早出境界時刻", max_length=10, initial="08:00",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "08:00"}),
    )
    standard_hours = forms.CharField(
        label="所定労働時間", max_length=10, initial="8.0",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "8.0"}),
    )
    break_minutes = forms.CharField(
        label="デフォルト休憩(分)", max_length=10, initial="60",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "60"}),
    )
    round_minutes = forms.CharField(
        label="丸め単位(分)", max_length=10, initial="0",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "0"}),
    )
    overtime_mode = forms.ChoiceField(
        label="残業計算モード",
        choices=[("clock", "時刻ベース"), ("hours", "時間ベース")],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
