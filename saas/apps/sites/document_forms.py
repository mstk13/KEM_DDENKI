"""現場の提出書類の入力（ADR-0065）。"""

from django import forms
from django.utils import timezone

from apps.sites import documents
from apps.sites.documents import ACCEPT_ATTR, UnsupportedDocumentFile, normalize_name
from apps.sites.models import DocumentPhase, SiteDocument


class MultipleDocumentInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleDocumentField(forms.FileField):
    """ファイルを何件かまとめて受け取り、リストで返す。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            MultipleDocumentInput(
                attrs={"accept": ACCEPT_ATTR, "multiple": True, "class": "form-control"}
            ),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            files = [f for f in data if f]
        else:
            files = [data] if data else []
        if not files:
            single_clean(None, initial)  # 必須ならここで「選んでください」になる
            return []
        return [single_clean(f, initial) for f in files]


class SiteDocumentUploadForm(forms.Form):
    """書類にファイルを置く。cleaned_data["files"] は (ファイル, 種類) の組のリスト。"""

    files = MultipleDocumentField(
        label="ファイル",
        help_text=(
            "PDF（.pdf）と Excel（.xlsx・.xls）を選べます。"
            f"まとめて {documents.MAX_DOCUMENT_FILES_PER_UPLOAD} 件まで、"
            f"1件 {documents.MAX_DOCUMENT_FILE_MB}MB まで。前に置いたファイルも残ります。"
        ),
    )
    note = forms.CharField(
        label="メモ",
        required=False,
        max_length=200,
        help_text="例: 第2版、提出用、発注者の確認印あり。選んだファイルすべてに付きます。",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def clean_files(self):
        files = self.cleaned_data["files"]
        limit = documents.MAX_DOCUMENT_FILES_PER_UPLOAD
        if len(files) > limit:
            raise forms.ValidationError(
                f"一度に登録できるのは {limit} 件までです（選ばれたのは {len(files)} 件）。"
                "分けて登録してください。"
            )
        max_bytes = documents.MAX_DOCUMENT_FILE_MB * 1024 * 1024
        errors = []
        uploads = []
        for uploaded in files:
            if uploaded.size > max_bytes:
                errors.append(
                    f"{uploaded.name}: {documents.MAX_DOCUMENT_FILE_MB}MB を超えています"
                )
                continue
            try:
                uploads.append((uploaded, documents.detect_file_kind(uploaded)))
            except UnsupportedDocumentFile as exc:
                errors.append(f"{uploaded.name}: {exc}")
        if errors:
            raise forms.ValidationError(errors)
        return uploads


class SiteDocumentForm(forms.ModelForm):
    """書類の状況・提出日・メモ。足した書類は名前も直せる。"""

    class Meta:
        model = SiteDocument
        fields = ["name", "status", "submitted_on", "note"]
        widgets = {
            "submitted_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.is_custom:
            # 最初のリストの書類の名前は、会社のリストと同じにしておく
            del self.fields["name"]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["submitted_on"].help_text = "「提出済み」で空欄なら今日にします。"
        self.fields["note"].help_text = "例: 発注者の監督員へ手渡し、再提出の指示あり"

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        duplicated = (
            SiteDocument.unscoped.filter(site=self.instance.site, name=name)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if duplicated:
            raise forms.ValidationError("この現場にはもう同じ名前の書類があります")
        return name

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == SiteDocument.Status.SUBMITTED:
            if not cleaned.get("submitted_on"):
                cleaned["submitted_on"] = timezone.localdate()
        else:
            # 提出日は「提出済み」のときだけ持つ
            cleaned["submitted_on"] = None
        return cleaned


class SiteDocumentAddForm(forms.Form):
    """リストに無い書類を名前を付けて足す。"""

    name = forms.CharField(
        label="書類名",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        help_text="例: 道路使用許可書、近隣挨拶文",
    )
    phase = forms.ChoiceField(
        label="時期",
        choices=DocumentPhase.choices,
        initial=DocumentPhase.OTHER,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    add_to_company_list = forms.BooleanField(
        label="次の現場からも最初のリストに入れる",
        required=False,
        help_text="チェックしなければ、この現場だけに足します。",
    )

    def __init__(self, *args, site, **kwargs):
        super().__init__(*args, **kwargs)
        self.site = site

    def clean_name(self):
        name = normalize_name(self.cleaned_data["name"])
        if not name:
            raise forms.ValidationError("書類名を入れてください")
        if SiteDocument.unscoped.filter(site=self.site, name=name).exists():
            raise forms.ValidationError("この現場にはもう同じ名前の書類があります")
        return name
