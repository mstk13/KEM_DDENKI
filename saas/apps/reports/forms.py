from django import forms

from apps.masters.models import Supplier, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker


class DailyReportForm(forms.ModelForm):
    class Meta:
        model = DailyReport
        fields = [
            "report_type", "site", "worker", "report_date", "weather",
            "process", "work_type", "work_description",
            "start_time", "end_time", "work_hours",
            "is_partner_worker", "partner",
            "memo",
        ]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "work_hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.25"}),
            "work_description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

        # 協力会社欄は「協力会社の作業員」にチェックが入ったときだけ表示する。
        # 表示切替は static/js/app.js が data-toggle-target を見て行う。
        self.fields["is_partner_worker"].widget.attrs["data-toggle-target"] = "partner"

        # start_time/end_time を入力したら work_hours は自動計算されるので任意に
        self.fields["work_hours"].required = False
        self.fields["start_time"].required = False
        self.fields["end_time"].required = False

        if company:
            self.fields["site"].queryset = Site.unscoped.filter(company=company)
            self.fields["worker"].queryset = Worker.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["process"].queryset = Process.unscoped.filter(company=company)
            self.fields["process"].required = False
            self.fields["partner"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["partner"].required = False

    def clean(self):
        cleaned = super().clean()

        # 協力会社は「協力会社の作業員」の場合のみ記入する。
        if cleaned.get("is_partner_worker"):
            if not cleaned.get("partner"):
                self.add_error("partner", "協力会社を選択してください。")
        else:
            cleaned["partner"] = None

        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        hours = cleaned.get("work_hours")

        # start_time/end_time が入力されていれば work_hours は不要
        if start and end:
            return cleaned

        # start_time/end_time がなければ work_hours は必須
        if not hours:
            self.add_error(
                "work_hours",
                "開始・終了時間を入力するか、作業時間を直接入力してください。",
            )
        return cleaned
