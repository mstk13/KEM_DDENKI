from django import forms


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
