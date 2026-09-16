"""自社書類の入力（ADR-0071）。"""

from django import forms

from apps.core import documents as core_documents
from apps.core.documents import ACCEPT_ATTR, UnsupportedDocumentFile
from apps.tenants.company_documents import normalize_name
from apps.tenants.models import CompanyDocument, CompanyDocumentType


class CompanyDocumentForm(forms.Form):
    """自社書類を1件登録する。種類は一覧から選ぶか、名前を付けて足す。"""

    doc_type = forms.ModelChoiceField(
        label="書類の種類",
        queryset=CompanyDocumentType.objects.none(),
        required=False,
        empty_label="（一覧に無い書類）",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    new_name = forms.CharField(
        label="一覧に無い書類の名前",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        help_text="種類で「一覧に無い書類」を選んだときに入れてください。会社の一覧にも足します。",
    )
    has_renewal = forms.BooleanField(
        label="更新がある書類にする",
        required=False,
        help_text="一覧に足すときだけ使います。更新日を入れると3か月前から知らせます。",
    )
    file = forms.FileField(
        label="ファイル",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ACCEPT_ATTR},
        ),
        help_text=(
            "PDF（.pdf）と Excel（.xlsx・.xls）。"
            f"1件 {core_documents.MAX_DOCUMENT_FILE_MB}MB まで。"
        ),
    )
    issued_on = forms.DateField(
        label="発行日",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    renewal_on = forms.DateField(
        label="更新日",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="次に更新・提出が必要な日。入れると3か月前・1か月前・2週間前に知らせます。",
    )
    memo = forms.CharField(
        label="メモ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
    )
    confirmed = forms.BooleanField(
        label="中身を確認しました",
        required=True,
        error_messages={"required": "中身を確認してから、チェックを入れて登録してください"},
        help_text="ファイルを開いて、中身と登録する種類・日付が合っていることを確かめてください。",
    )

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        # unscoped: 会社を引数で受けて明示的に絞る（定時実行・他社の種類を出さない）
        self.fields["doc_type"].queryset = CompanyDocumentType.unscoped.filter(
            company=company, is_active=True,
        ).order_by("-has_renewal", "display_order", "pk")

    def clean_new_name(self):
        return normalize_name(self.cleaned_data["new_name"])

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        max_bytes = core_documents.MAX_DOCUMENT_FILE_MB * 1024 * 1024
        if uploaded.size > max_bytes:
            raise forms.ValidationError(
                f"{core_documents.MAX_DOCUMENT_FILE_MB}MB を超えるファイルは登録できません"
            )
        try:
            self.file_kind = core_documents.detect_file_kind(uploaded)
        except UnsupportedDocumentFile as exc:
            raise forms.ValidationError(str(exc)) from exc
        return uploaded

    def clean(self):
        cleaned = super().clean()
        doc_type = cleaned.get("doc_type")
        new_name = cleaned.get("new_name")
        if doc_type is None and not new_name:
            raise forms.ValidationError("書類の種類を選ぶか、一覧に無い書類の名前を入れてください")
        if doc_type is not None and new_name:
            # どちらも入っていると、どちらの名前で残すのか決められない
            raise forms.ValidationError(
                "種類を選んだときは、一覧に無い書類の名前を空にしてください"
            )
        if new_name and CompanyDocumentType.unscoped.filter(
            company=self.company, name=new_name,
        ).exists():
            raise forms.ValidationError(
                "その名前の種類はもう一覧にあります。種類から選んでください"
            )
        return cleaned


class CompanyDocumentEditForm(forms.ModelForm):
    """登録した書類の日付・メモを直す。ファイルの入れ替えは新しく登録する。"""

    class Meta:
        model = CompanyDocument
        fields = ["issued_on", "renewal_on", "memo"]
        widgets = {
            "issued_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "renewal_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "memo": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
