from pathlib import Path

from django import forms

from apps.accounts.models import User
from apps.masters.models import Customer, WorkType
from apps.sites.models import Process, Site
from apps.sites.services import resolve_or_create_customer


class SiteForm(forms.ModelForm):
    """現場の登録・編集フォーム。

    顧客は FK のプルダウンではなく**自由入力**にしている。未登録の会社名を
    その場で書けないと、現場の顧客を後から直すのに「先に顧客マスタへ登録して
    から現場を編集する」という2画面の往復が要るため。入力値は
    resolve_or_create_customer が引き当て、未登録なら顧客マスタに登録する。
    """

    customer_name = forms.CharField(
        label="顧客",
        required=False,
        help_text="登録済みの会社は候補から選べます。未登録の会社名を直接入力すると顧客マスタにも登録されます。",
    )

    class Meta:
        model = Site
        fields = [
            "code", "name", "status",
            "contract_amount", "payment_terms", "estimate_valid_until",
            "start_date", "end_date",
            "manager", "estimator", "address", "note", "extracted_details",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "extracted_details": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
        }

    def __init__(self, *args, company=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._company = company
        self._user = user
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["manager"].queryset = User.objects.filter(company=company)
            self.fields["estimator"].queryset = User.objects.filter(company=company)
            # 入力補助の候補。datalist なのでこの一覧に無い名前も送信できる。
            self.customer_choices = list(
                Customer.unscoped.filter(company=company, is_active=True)
                .order_by("name")
                .values_list("name", flat=True)
            )
        else:
            self.customer_choices = []

        self.fields["customer_name"].widget.attrs["list"] = "customer-name-options"
        if self.instance.pk and self.instance.customer_id:
            self.fields["customer_name"].initial = self.instance.customer.name

    def save(self, commit=True):
        site = super().save(commit=False)
        # 新規登録では site.company をビューが後から入れるので、フォームに渡された
        # company を優先する。どちらも無いときは顧客を触らない（取り違えを防ぐ）。
        company = self._company or (site.company if site.company_id else None)
        if company is not None:
            site.customer = resolve_or_create_customer(
                company,
                self.cleaned_data.get("customer_name"),
                created_by=self._user,
            )
        if commit:
            site.save()
            self.save_m2m()
        return site


class EstimateUploadForm(forms.Form):
    """見積ファイル（ライデンの CSV / Excel、見積書の PDF）を受け取るフォーム。"""

    ALLOWED_SUFFIXES = (".csv", ".xlsx", ".xlsm", ".pdf")

    file = forms.FileField(
        label="見積ファイル",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".csv,.xlsx,.xlsm,.pdf", "class": "form-control"}
        ),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        suffix = Path(uploaded.name).suffix.lower()
        if suffix == ".xls":
            # openpyxl は旧形式を読めないので、拡張子の時点で理由を伝える。
            raise forms.ValidationError(
                "古い Excel 形式(.xls)は読めません。"
                "Excel で開いて .xlsx で保存し直してから選んでください。"
            )
        if suffix not in self.ALLOWED_SUFFIXES:
            raise forms.ValidationError(
                "CSV(.csv) / Excel(.xlsx) / PDF(.pdf) を選んでください。"
                f"（選ばれたのは {suffix or '拡張子なし'} です）"
            )
        return uploaded


class ProcessForm(forms.ModelForm):
    """現場の工程を手入力するためのフォーム。"""

    class Meta:
        model = Process
        fields = [
            "name", "work_type", "planned_start", "planned_end",
            "actual_start", "actual_end", "status", "display_order",
        ]
        widgets = {
            "planned_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "planned_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "actual_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "actual_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )

    def clean(self):
        cleaned = super().clean()
        for start_key, end_key, label in (
            ("planned_start", "planned_end", "計画"),
            ("actual_start", "actual_end", "実績"),
        ):
            start = cleaned.get(start_key)
            end = cleaned.get(end_key)
            if start and end and end < start:
                self.add_error(
                    end_key, f"{label}終了日は{label}開始日以降にしてください。"
                )
        return cleaned
