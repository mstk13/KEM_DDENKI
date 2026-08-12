from django import forms

from apps.masters.models import Supplier, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker


def _next_code(queryset, prefix):
    """手入力で新規登録するときのコードを採番する。

    コードは (company, code) で一意なので、重複しない値が要る。
    """
    used = set(queryset.values_list("code", flat=True))
    n = 1
    while f"{prefix}{n:04d}" in used:
        n += 1
    return f"{prefix}{n:04d}"


class DailyReportForm(forms.ModelForm):
    """日報の入力フォーム。

    現場・天候・工程・工種は、一覧から選ぶことも手入力することもできる。
    HTML の datalist を使い、入力された名前が既存に無ければ登録する。

    現場・工程・工種は Meta.fields に含めず、save() で解決してから
    instance に入れている。検証中に登録すると、他の欄でエラーになったとき
    使われない現場や工種だけが残ってしまうため。
    """

    # 現場から自動で引く発注先。表示専用で、日報には保存しない。
    orderer = forms.CharField(
        label="発注先",
        required=False,
        widget=forms.TextInput(attrs={"readonly": "readonly"}),
    )
    site = forms.CharField(
        label="現場",
        widget=forms.TextInput(attrs={"list": "site-list", "autocomplete": "off"}),
    )
    weather = forms.CharField(
        label="天候",
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={"list": "weather-list", "autocomplete": "off"}),
    )
    process = forms.CharField(
        label="工程",
        required=False,
        widget=forms.TextInput(attrs={"list": "process-list", "autocomplete": "off"}),
    )
    work_type = forms.CharField(
        label="工種",
        widget=forms.TextInput(attrs={"list": "worktype-list", "autocomplete": "off"}),
    )

    field_order = [
        "report_type", "site", "orderer", "worker", "report_date", "weather",
        "process", "work_type", "work_description",
        "start_time", "end_time", "work_hours",
        "is_partner_worker", "partner", "memo",
    ]

    class Meta:
        model = DailyReport
        # site / process / work_type は save() で入れるためここには含めない
        fields = [
            "report_type", "worker", "report_date", "weather",
            "work_description",
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
        self.company = company

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
            self.fields["worker"].queryset = Worker.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["partner"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["partner"].required = False

        # 編集時は、名前で入力する欄に現在の値を表示する
        obj = self.instance
        if obj and obj.pk:
            self.initial["site"] = obj.site.name if obj.site_id else ""
            self.initial["process"] = obj.process.name if obj.process_id else ""
            self.initial["work_type"] = obj.work_type.name if obj.work_type_id else ""
            if obj.site_id and obj.site.customer_id:
                self.initial["orderer"] = str(obj.site.customer)

    def clean_site(self):
        name = (self.cleaned_data.get("site") or "").strip()
        if not name:
            raise forms.ValidationError("現場を入力してください。")
        return name

    def clean_work_type(self):
        name = (self.cleaned_data.get("work_type") or "").strip()
        if not name:
            raise forms.ValidationError("工種を入力してください。")
        return name

    def clean_process(self):
        return (self.cleaned_data.get("process") or "").strip()

    def clean(self):
        cleaned = super().clean()

        if not self.company:
            raise forms.ValidationError(
                "会社が特定できないため保存できません。管理者に連絡してください。",
            )

        # 協力会社は「協力会社の作業員」の場合のみ記入する。
        if cleaned.get("is_partner_worker"):
            if not cleaned.get("partner"):
                self.add_error("partner", "協力会社を選択してください。")
        else:
            cleaned["partner"] = None

        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        hours = cleaned.get("work_hours")

        # start_time/end_time が入力されていれば work_hours は自動計算される
        if start and end:
            return cleaned

        if not hours:
            self.add_error(
                "work_hours",
                "開始・終了時間を入力するか、作業時間を直接入力してください。",
            )
        return cleaned

    def _resolve_site(self, name):
        site = Site.unscoped.filter(company=self.company, name=name).first()
        if site:
            return site
        code = _next_code(Site.unscoped.filter(company=self.company), "S")
        return Site.unscoped.create(company=self.company, code=code, name=name)

    def _resolve_work_type(self, name):
        work_type = WorkType.unscoped.filter(company=self.company, name=name).first()
        if work_type:
            return work_type
        code = _next_code(WorkType.unscoped.filter(company=self.company), "W")
        return WorkType.unscoped.create(company=self.company, code=code, name=name)

    def _resolve_process(self, name, site, work_type):
        if not name:
            return None
        process = Process.unscoped.filter(
            company=self.company, site=site, name=name,
        ).first()
        if process:
            return process
        return Process.unscoped.create(
            company=self.company, site=site, work_type=work_type, name=name,
        )

    def save(self, commit=True):
        report = super().save(commit=False)

        site = self._resolve_site(self.cleaned_data["site"])
        work_type = self._resolve_work_type(self.cleaned_data["work_type"])

        report.site = site
        report.work_type = work_type
        report.process = self._resolve_process(
            self.cleaned_data.get("process"), site, work_type,
        )

        if commit:
            report.save()
        return report
