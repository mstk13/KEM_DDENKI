from django import forms
from django.db.models import Case, IntegerField, Q, Value, When

from apps.masters.models import Supplier, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker


# 日報の書式は、ログインした人の社員番号の接頭辞で決まる。
#   E（電工・事務の正社員）・T（試用期間） … 現場作業の日報
#   G（Developer）・S（役員）・A（アルバイト）・P（パート） … 事務の日報
# 上記以外（Y=社長 / W=その他 / 社員番号なし）は現場作業の日報を既定とする。
OFFICE_CODE_PREFIXES = ("G", "S", "A", "P")
FIELD_CODE_PREFIXES = ("E", "T")

# 事務の日報に付ける工種。現場ごとの原価区分を保つため、無ければ作る。
OFFICE_WORK_TYPE_NAME = "事務"


def is_office_reporter(user):
    """ログインした人が「事務の日報」を書く区分かどうか。"""
    profile = getattr(user, "worker_profile", None)
    code = getattr(profile, "employee_code", "") or ""
    return code.startswith(OFFICE_CODE_PREFIXES)


def _next_code(queryset, prefix):
    """手入力で新規登録するときのコードを採番する。

    コードは (company, code) で一意なので、重複しない値が要る。
    """
    used = set(queryset.values_list("code", flat=True))
    n = 1
    while f"{prefix}{n:04d}" in used:
        n += 1
    return f"{prefix}{n:04d}"


def resolve_site(company, name):
    """現場名から現場を引く。無ければ登録する（コードは自動採番）。"""
    site = Site.unscoped.filter(company=company, name=name).first()
    if site:
        return site
    code = _next_code(Site.unscoped.filter(company=company), "S")
    return Site.unscoped.create(company=company, code=code, name=name)


def resolve_work_type(company, name):
    """工種名から工種を引く。無ければ登録する。"""
    work_type = WorkType.unscoped.filter(company=company, name=name).first()
    if work_type:
        return work_type
    code = _next_code(WorkType.unscoped.filter(company=company), "W")
    return WorkType.unscoped.create(company=company, code=code, name=name)


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

    # 1日報＝1作業員（現場・作業員・日付・工種で一意）なので、
    # 複数選ばれたときは人数分の日報を作る。
    workers = forms.ModelMultipleChoiceField(
        label="作業員",
        # 読み込み時に評価されるため、テナント判定を通らない unscoped を使う。
        # 実際の候補は __init__ で会社ごとに絞る。
        queryset=Worker.unscoped.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    field_order = [
        "site", "orderer", "workers", "report_date", "weather",
        "process", "work_type", "work_description",
        "start_time", "end_time", "work_hours",
        "is_partner_worker", "partner", "memo",
    ]

    class Meta:
        model = DailyReport
        # site / process / work_type / worker は save 時に入れるため含めない。
        # 種別（report_type）は入力しない（モデルの既定値のまま）。
        fields = [
            "report_date", "weather",
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

        self.is_edit = bool(self.instance and self.instance.pk)

        for name, field in self.fields.items():
            # チェックボックス群に form-control を付けると枠線が二重になる
            if name != "workers":
                field.widget.attrs.setdefault("class", "form-control")

        # 協力会社欄は「協力会社の作業員」にチェックが入ったときだけ表示する。
        # 表示切替は static/js/app.js が data-toggle-target を見て行う。
        self.fields["is_partner_worker"].widget.attrs["data-toggle-target"] = "partner"

        # start_time/end_time を入力したら work_hours は自動計算されるので任意に
        self.fields["work_hours"].required = False
        self.fields["start_time"].required = False
        self.fields["end_time"].required = False

        if company:
            # 日報を書くのは社員番号が E で始まる作業員のみ。
            # 並びはフリガナの50音順（未登録の人は氏名で並べ、後ろに回す）。
            self.fields["workers"].queryset = (
                Worker.unscoped.filter(
                    company=company, is_active=True, employee_code__startswith="E",
                )
                .annotate(
                    kana_missing=Case(
                        When(Q(name_kana="") | Q(name_kana__isnull=True), then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                )
                .order_by("kana_missing", "name_kana", "name")
            )
            self.fields["partner"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["partner"].required = False

        # 編集時は、名前で入力する欄に現在の値を表示する
        obj = self.instance
        if self.is_edit:
            self.initial["site"] = obj.site.name if obj.site_id else ""
            self.initial["process"] = obj.process.name if obj.process_id else ""
            self.initial["work_type"] = obj.work_type.name if obj.work_type_id else ""
            self.initial["workers"] = [obj.worker_id] if obj.worker_id else []
            if obj.site_id and obj.site.customer_id:
                self.initial["orderer"] = str(obj.site.customer)

    def clean_workers(self):
        workers = self.cleaned_data.get("workers")
        if self.is_edit and workers and len(workers) > 1:
            raise forms.ValidationError(
                "編集画面では作業員は1人だけ選べます。"
                "他の作業員の日報は、それぞれの日報から編集してください。",
            )
        return workers

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
        return resolve_site(self.company, name)

    def _resolve_work_type(self, name):
        return resolve_work_type(self.company, name)

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
        """保存は save_reports() を使う。

        現場・工種・作業員は save_reports() で入れるため、ここで commit すると
        必須項目が空のまま保存しようとして落ちる。取り違えを早く気づけるようにする。
        """
        if commit:
            raise NotImplementedError(
                "DailyReportForm の保存は save_reports() を使ってください。",
            )
        return super().save(commit=False)

    def save_reports(self, *, company, user, status=None):
        """選ばれた作業員の人数分の日報を保存する。

        1日報＝1作業員（現場・作業員・日付・工種で一意）なので、
        複数選ばれたときは同じ内容の日報を人数分つくる。

        戻り値は (保存した日報のリスト, 既にあって飛ばした作業員のリスト)。
        """
        from django.db import IntegrityError, transaction

        site = self._resolve_site(self.cleaned_data["site"])
        work_type = self._resolve_work_type(self.cleaned_data["work_type"])
        process = self._resolve_process(
            self.cleaned_data.get("process"), site, work_type,
        )

        proto = super().save(commit=False)
        proto.site = site
        proto.work_type = work_type
        proto.process = process
        if status is not None:
            proto.status = status

        saved, skipped = [], []
        for worker in self.cleaned_data["workers"]:
            if self.is_edit:
                proto.worker = worker
                proto.save()
                saved.append(proto)
                continue

            report = DailyReport(
                company=company,
                created_by=user,
                site=site,
                work_type=work_type,
                process=process,
                worker=worker,
                report_date=proto.report_date,
                weather=proto.weather,
                work_description=proto.work_description,
                start_time=proto.start_time,
                end_time=proto.end_time,
                work_hours=proto.work_hours,
                is_partner_worker=proto.is_partner_worker,
                partner=proto.partner,
                memo=proto.memo,
                status=proto.status,
            )
            try:
                # 同じ現場・日付・工種で既に日報がある作業員は飛ばす。
                # 1件の失敗で他の作業員の保存まで巻き戻さないよう個別に囲う。
                with transaction.atomic():
                    report.save()
            except IntegrityError:
                skipped.append(worker)
                continue
            saved.append(report)

        return saved, skipped


class OfficeDailyReportForm(forms.Form):
    """事務の日報（社員番号が G / S / A / P で始まる人向け）。

    1日ぶんの勤務時間を1回だけ入力し、その日に携わった現場を必要な数だけ
    「現場追加」ボタンで足していく。現場ごとに作業内容を書く。

    保存すると現場1件につき日報1件をつくる（現場・作業員・日付・工種で一意）。
    勤務時間は最初の現場にだけ計上する。全件に入れると勤怠が二重になるため。
    """

    report_date = forms.DateField(
        label="日付",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    start_time = forms.TimeField(
        label="開始時間",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
    )
    end_time = forms.TimeField(
        label="終了時間",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
    )
    work_hours = forms.DecimalField(
        label="作業時間",
        required=False,
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.25"}),
    )
    memo = forms.CharField(
        label="その他",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def __init__(self, *args, company=None, worker=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.worker = worker
        # clean() で組み立てた現場ごとの入力を保持する
        self.entries = []

    def clean(self):
        cleaned = super().clean()

        if not self.company:
            raise forms.ValidationError(
                "会社が特定できないため保存できません。管理者に連絡してください。",
            )
        if not self.worker:
            raise forms.ValidationError(
                "ログイン中のアカウントに作業員が紐づいていないため保存できません。"
                "管理者に連絡してください。",
            )

        # 現場ブロックは site_1 / work_description_1 … の組で送られてくる。
        # 画面で「現場追加」を押すたびに番号が増えるため、順番に拾う。
        entries = []
        for key in self.data:
            if not key.startswith("site_"):
                continue
            suffix = key[len("site_"):]
            name = (self.data.get(key) or "").strip()
            if not name:
                continue
            entries.append({
                "suffix": suffix,
                "site_name": name,
                "work_description": (
                    self.data.get(f"work_description_{suffix}") or ""
                ).strip(),
            })
        entries.sort(key=lambda e: e["suffix"])

        if not entries:
            raise forms.ValidationError("現場を1つ以上追加してください。")

        # 同じ現場を2回書くと、日報が一意制約で作れない
        names = [e["site_name"] for e in entries]
        duplicated = {n for n in names if names.count(n) > 1}
        if duplicated:
            raise forms.ValidationError(
                "同じ現場が複数あります: " + "、".join(sorted(duplicated)),
            )

        self.entries = entries

        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        if not (start and end) and not cleaned.get("work_hours"):
            self.add_error(
                "work_hours",
                "開始・終了時間を入力するか、作業時間を直接入力してください。",
            )
        return cleaned

    def save_reports(self, *, user, status=None):
        """現場ごとに日報をつくる。戻り値は (保存した日報, 飛ばした現場名)。"""
        from django.db import IntegrityError, transaction

        work_type = resolve_work_type(self.company, OFFICE_WORK_TYPE_NAME)
        report_date = self.cleaned_data["report_date"]

        saved, skipped = [], []
        for index, entry in enumerate(self.entries):
            site = resolve_site(self.company, entry["site_name"])
            first = index == 0

            report = DailyReport(
                company=self.company,
                created_by=user,
                site=site,
                worker=self.worker,
                work_type=work_type,
                report_date=report_date,
                work_description=entry["work_description"],
                memo=self.cleaned_data.get("memo", "") if first else "",
                # 勤務時間は最初の現場にだけ計上する
                start_time=self.cleaned_data.get("start_time") if first else None,
                end_time=self.cleaned_data.get("end_time") if first else None,
                work_hours=(
                    self.cleaned_data.get("work_hours") or 0 if first else 0
                ),
            )
            if status is not None:
                report.status = status

            try:
                with transaction.atomic():
                    report.save()
            except IntegrityError:
                skipped.append(entry["site_name"])
                continue
            saved.append(report)

        return saved, skipped
