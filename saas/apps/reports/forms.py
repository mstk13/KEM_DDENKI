from django import forms

from apps.masters.models import Supplier, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker, sort_workers_by_code

# 日報は役職・社員番号に関係なく全員が同じ形式で書く（ADR-0043）。
# 社員番号が E・T の人は「現場」として作業員の左の列に、それ以外は右の列に出す。
FIELD_CODE_PREFIXES = ("E", "T")

# 現場作業の日報で工程として最初から選べるもの。この順で候補の先頭に出す。
# 工程は現場ごとに持つ（Process は site に紐づく）ので、事前には登録せず、
# 日報を保存したときにその現場の工程として登録する（_resolve_process）。
STANDARD_PROCESS_NAMES = ("見積り", "現調", "施工", "試験", "追加工事", "納入")

# 工程の選択肢で「一覧に無い工程を入力する」を表す値
PROCESS_OTHER = "__other__"


def is_field_worker(worker):
    """現場作業の区分（社員番号が E・T で始まる）かどうか。"""
    code = (getattr(worker, "employee_code", "") or "").strip()
    return code.startswith(FIELD_CODE_PREFIXES)


def _next_code(queryset, prefix):
    """手入力で新規登録するときのコードを採番する。

    コードは (company, code) で一意なので、重複しない値が要る。
    """
    used = set(queryset.values_list("code", flat=True))
    n = 1
    while f"{prefix}{n:04d}" in used:
        n += 1
    return f"{prefix}{n:04d}"


def clean_work_period(form, cleaned):
    """開始日・終了日・時刻の整合性をそろえる（現場作業・事務の日報で共通）。

    - 開始日が空なら日報の日付を開始日とみなす
    - 終了日が開始日より前はエラー
    - 同じ日で終了時刻が開始以前なら翌日の作業とみなし、終了日を翌日に直す
      （日付が無かったときの従来の扱いと同じ）
    """
    from datetime import timedelta

    start = cleaned.get("start_time")
    end = cleaned.get("end_time")
    start_day = cleaned.get("start_date") or cleaned.get("report_date")
    end_day = cleaned.get("end_date")
    if end_day and start_day and end_day < start_day:
        form.add_error("end_date", "終了日は開始日より前にできません。")
    elif end_day and start_day and start and end and end_day == start_day and end <= start:
        cleaned["end_date"] = end_day + timedelta(days=1)


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


def process_choice_names(company):
    """日報で選べる工程名。標準の工程を決まった順で先に、その後に会社で使われている工程を名前順で。

    「その他」で入力して登録された工程もここに入るので、次回から候補として選べる。
    """
    used = set(
        Process.unscoped.filter(company=company).values_list("name", flat=True)
    )
    others = sorted(name for name in used if name not in STANDARD_PROCESS_NAMES)
    return list(STANDARD_PROCESS_NAMES) + others


class DailyReportForm(forms.ModelForm):
    """日報の入力フォーム。

    現場・天候・工種は、一覧から選ぶことも手入力することもできる。
    HTML の datalist を使い、入力された名前が既存に無ければ登録する。

    工程は選択式。標準の工程（見積り・現調・施工・試験・追加工事・納入）を先頭に、
    会社で使われている工程を並べる。一覧に無い工程は「その他」を選んで process_other に
    入力すると、その現場の工程として登録され、次回から候補に出る。

    開始・終了は時刻だけでなく日付も入れられる（夜間工事などで日をまたぐため）。
    日付が空なら日報の日付の作業として扱う。

    現場・工程・工種は Meta.fields に含めず、save() で解決してから
    instance に入れている。検証中に登録すると、他の欄でエラーになったとき
    使われない現場や工種だけが残ってしまうため。

    天候も Meta.fields に含めない。含めると ModelForm が保存前にモデルの
    選択肢と突き合わせ、選択肢に無い言葉が「有効な選択肢ではありません」で
    弾かれてしまう（自由入力にした意味が無くなる）。
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
        widget=forms.Select(),
    )
    process_other = forms.CharField(
        label="新しい工程",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "例: 保守点検", "autocomplete": "off"}),
    )
    work_type = forms.CharField(
        label="工種",
        widget=forms.TextInput(attrs={"list": "worktype-list", "autocomplete": "off"}),
    )

    # 1日報＝1作業員（現場・作業員・日付・工種で一意）なので、
    # 複数選ばれたときは人数分の日報を作る。
    # 人ごとに時間が違うときは、作業員の行の start_time_<pk> / end_time_<pk> に
    # 入れると、その人だけ共通の時間の代わりに使う（__init__ で人数分つくる）。
    workers = forms.ModelMultipleChoiceField(
        label="作業員の日報をまとめて書く",
        # 読み込み時に評価されるため、テナント判定を通らない unscoped を使う。
        # 実際の候補は __init__ で会社ごとに絞る。
        queryset=Worker.unscoped.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    field_order = [
        "site", "orderer", "workers", "report_date", "weather",
        "process", "process_other", "work_type", "work_description",
        "start_date", "start_time", "end_date", "end_time", "work_hours",
        "is_partner_worker", "partner", "memo",
    ]

    class Meta:
        model = DailyReport
        # site / process / work_type / worker は save 時に入れるため含めない。
        # 種別（report_type）は入力しない（モデルの既定値のまま）。
        fields = [
            "report_date",
            "work_description",
            "start_date", "start_time", "end_date", "end_time", "work_hours",
            "is_partner_worker", "partner",
            "memo",
        ]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
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
        for name in ("start_date", "start_time", "end_date", "end_time"):
            self.fields[name].required = False

        if company:
            names = process_choice_names(company)
            # 編集中の日報の工程が候補に無くても、選び直せるよう候補に残す
            current = (
                self.instance.process.name
                if self.is_edit and self.instance.process_id else ""
            )
            if current and current not in names:
                names.append(current)
            self.fields["process"].widget.choices = [
                ("", "（なし）"),
                *((name, name) for name in names),
                (PROCESS_OTHER, "その他（新しい工程を入力）"),
            ]

            # 候補は在籍中の全員。画面では現場作業の区分（E・T）を左、
            # それ以外（事務など。現場に出ることもある）を右に分けて出す。
            # 並びは作業員一覧と同じ社員番号順（_build_worker_rows で並べる）。
            self.fields["workers"].queryset = Worker.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["partner"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["partner"].required = False

        # 新規作成では、作業員ごとに時間を変えられる欄を人数分つくる。
        # 編集は1人だけなので共通の欄で足りる。
        self.worker_rows = []
        if not self.is_edit:
            self._build_worker_rows()

        # 編集で、まとめて作った他の人の日報にも反映するかどうか。
        # 同じ組の日報が無ければ欄を出さない。
        self.batch_siblings = []
        if self.is_edit and self.instance.batch:
            self.batch_siblings = list(
                self.instance.batch_siblings().exclude(
                    status=DailyReport.Status.APPROVED,
                ).order_by("worker__name"),
            )
            if self.batch_siblings:
                self.fields["apply_to_batch"] = forms.BooleanField(
                    label="一緒に作った他の作業員の日報にも反映する",
                    required=False,
                    initial=True,
                )

        # 編集時は、名前で入力する欄に現在の値を表示する
        obj = self.instance
        if self.is_edit:
            self.initial["site"] = obj.site.name if obj.site_id else ""
            self.initial["process"] = obj.process.name if obj.process_id else ""
            self.initial["work_type"] = obj.work_type.name if obj.work_type_id else ""
            self.initial["workers"] = [obj.worker_id] if obj.worker_id else []
            self.initial["weather"] = obj.weather
            if obj.site_id and obj.site.customer_id:
                self.initial["orderer"] = str(obj.site.customer)

    def _build_worker_rows(self):
        """作業員ごとの行（チェック＋その人だけの開始・終了時刻・作業時間）をつくる。

        worker_rows は全員、worker_rows_field は E・T、worker_rows_other はそれ以外。
        """
        if self.is_bound:
            # テストなどで素の dict が渡ることもあるので getlist に頼らない
            if hasattr(self.data, "getlist"):
                raw = self.data.getlist("workers")
            else:
                raw = self.data.get("workers") or []
                if not isinstance(raw, (list, tuple)):
                    raw = [raw]
            selected = {str(v) for v in raw}
        else:
            selected = {str(v) for v in (self.initial.get("workers") or [])}
        time_attrs = {"type": "time", "class": "form-control"}
        self.worker_rows_field = []
        self.worker_rows_other = []
        for worker in sort_workers_by_code(self.fields["workers"].queryset):
            start_name = f"start_time_{worker.pk}"
            end_name = f"end_time_{worker.pk}"
            hours_name = f"work_hours_{worker.pk}"
            self.fields[start_name] = forms.TimeField(
                required=False, widget=forms.TimeInput(attrs=dict(time_attrs)),
            )
            self.fields[end_name] = forms.TimeField(
                required=False, widget=forms.TimeInput(attrs=dict(time_attrs)),
            )
            self.fields[hours_name] = forms.DecimalField(
                required=False, min_value=0, max_digits=5, decimal_places=2,
                widget=forms.NumberInput(attrs={
                    "class": "form-control", "step": "0.25", "placeholder": "時間",
                }),
            )
            row = {
                "worker": worker,
                "checked": str(worker.pk) in selected,
                "start": self[start_name],
                "end": self[end_name],
                "hours": self[hours_name],
            }
            self.worker_rows.append(row)
            if is_field_worker(worker):
                self.worker_rows_field.append(row)
            else:
                self.worker_rows_other.append(row)

    # テンプレートの通常ループで出さない欄（作業員の行や編集の反映欄で別に出す）
    @property
    def side_field_names(self):
        names = {"apply_to_batch"}
        for row in self.worker_rows:
            names.add(row["start"].name)
            names.add(row["end"].name)
            names.add(row["hours"].name)
        return names

    def worker_times(self, worker):
        """その作業員だけの (開始時刻, 終了時刻)。両方入っていなければ None。"""
        start = self.cleaned_data.get(f"start_time_{worker.pk}")
        end = self.cleaned_data.get(f"end_time_{worker.pk}")
        if start and end:
            return start, end
        return None

    def worker_hours(self, worker):
        """その作業員だけの作業時間。空なら None。"""
        return self.cleaned_data.get(f"work_hours_{worker.pk}") or None

    def clean_workers(self):
        workers = self.cleaned_data.get("workers")
        if self.is_edit and workers and len(workers) > 1:
            raise forms.ValidationError(
                "編集画面では作業員は1人だけ選べます。"
                "他の作業員の日報は、それぞれの日報から編集してください。",
            )
        return workers

    def clean_weather(self):
        """選択肢の表示名で入力されたら、保存値に直す。

        候補には「晴」「曇」と出るが、モデルは "sunny" "cloudy" で持っている。
        そのまま保存すると既存データと表記が混ざるため、既知のものは寄せる。
        選択肢に無い言葉はそのまま保存する。
        """
        text = (self.cleaned_data.get("weather") or "").strip()
        if not text:
            return ""
        for value, label in DailyReport.Weather.choices:
            if text in (value, label):
                return value
        return text

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

    def clean_process_other(self):
        return (self.cleaned_data.get("process_other") or "").strip()

    def clean(self):
        cleaned = super().clean()

        if not self.company:
            raise forms.ValidationError(
                "会社が特定できないため保存できません。管理者に連絡してください。",
            )

        # 工程で「その他」を選んだら、入力された名前を工程にする
        # （save でその現場の工程として登録される）
        if cleaned.get("process") == PROCESS_OTHER:
            other = cleaned.get("process_other") or ""
            if other:
                cleaned["process"] = other
            else:
                self.add_error("process_other", "新しい工程を入力してください。")

        # 協力会社は「協力会社の作業員」の場合のみ記入する。
        if cleaned.get("is_partner_worker"):
            if not cleaned.get("partner"):
                self.add_error("partner", "協力会社を選択してください。")
        else:
            cleaned["partner"] = None

        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        hours = cleaned.get("work_hours")

        clean_work_period(self, cleaned)

        # 作業員ごとの時間は、開始・終了の片方だけでは計算できない
        for row in self.worker_rows:
            if not row["checked"]:
                continue
            w_start = cleaned.get(row["start"].name)
            w_end = cleaned.get(row["end"].name)
            if bool(w_start) != bool(w_end):
                self.add_error(
                    row["end"].name if w_start else row["start"].name,
                    f"{row['worker'].name} の開始・終了時刻は両方入れてください。",
                )

        # start_time/end_time が入力されていれば work_hours は自動計算される
        if start and end:
            return cleaned

        # 共通の時間が無くても、選ばれた全員に個別の時間か作業時間が入っていれば足りる
        chosen = cleaned.get("workers")
        if chosen and not self.is_edit and all(
            self.worker_times(w) or self.worker_hours(w) for w in chosen
        ):
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

    # 同じ組の日報に写す内容。時間は人ごとに違うことがあるので別扱い（下）。
    BATCH_SHARED_FIELDS = (
        "site", "work_type", "process", "report_date", "weather",
        "work_description", "is_partner_worker", "partner", "memo",
    )
    TIME_FIELDS = ("start_date", "start_time", "end_date", "end_time", "work_hours")

    def save_reports(self, *, company, user, status=None):
        """選ばれた作業員の人数分の日報を保存する。

        1日報＝1作業員（現場・作業員・日付・工種で一意）なので、
        複数選ばれたときは同じ内容の日報を人数分つくる。人ごとの時刻が
        入っていればその人だけ共通の時刻の代わりに使う。2人以上のときは
        同じ組（batch）の印を付け、後で代表者が直したときに揃えられるようにする。

        編集で「他の作業員の日報にも反映」が付いていれば、同じ組の日報に
        内容を写す（self.propagated / self.propagate_skipped に結果を入れる）。

        戻り値は (保存した日報のリスト, 既にあって飛ばした作業員のリスト)。
        """
        import uuid

        from django.db import IntegrityError, transaction

        site = self._resolve_site(self.cleaned_data["site"])
        work_type = self._resolve_work_type(self.cleaned_data["work_type"])
        process = self._resolve_process(
            self.cleaned_data.get("process"), site, work_type,
        )

        # 編集前の時間。同じ組の日報のうち、時間がこれと同じだった人だけ時間も揃える
        before_times = None
        if self.is_edit:
            original = DailyReport.unscoped.get(pk=self.instance.pk)
            before_times = {name: getattr(original, name) for name in self.TIME_FIELDS}

        proto = super().save(commit=False)
        proto.site = site
        proto.work_type = work_type
        proto.process = process
        proto.weather = self.cleaned_data.get("weather", "")
        if status is not None:
            proto.status = status

        self.propagated = []
        self.propagate_skipped = []

        workers = list(self.cleaned_data["workers"])
        batch = uuid.uuid4() if (not self.is_edit and len(workers) > 1) else None

        saved, skipped = [], []
        for worker in workers:
            if self.is_edit:
                proto.worker = worker
                proto.save()
                saved.append(proto)
                if self.cleaned_data.get("apply_to_batch"):
                    self._propagate_to_batch(proto, before_times)
                continue

            times = self.worker_times(worker)
            own_hours = self.worker_hours(worker)
            # 作業時間の優先順:
            #   その人の開始・終了があれば、モデルの save がそこから計算する
            #   無くてその人の作業時間があれば、その値（共通の開始・終了は
            #   その人には当てはまらないので入れない。入れると save で上書きされる）
            #   どちらも無ければ共通の値
            if times:
                start_time, end_time = times
                hours = proto.work_hours or 0
            elif own_hours:
                start_time, end_time = None, None
                hours = own_hours
            else:
                start_time, end_time = proto.start_time, proto.end_time
                hours = proto.work_hours or 0
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
                start_date=proto.start_date if start_time else None,
                start_time=start_time,
                end_date=proto.end_date if end_time else None,
                end_time=end_time,
                work_hours=hours,
                is_partner_worker=proto.is_partner_worker,
                partner=proto.partner,
                memo=proto.memo,
                status=proto.status,
                batch=batch,
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

    def _propagate_to_batch(self, report, before_times):
        """同じ組の日報に内容を写す。承認済みは触らない。

        時間は、編集前のこの日報と同じ時間だった人だけ新しい時間に揃える
        （人ごとに変えてあった時間はそのまま残す）。
        現場・日付・工種を変えた結果、その人の別の日報とぶつかるものは飛ばす。
        """
        from django.db import IntegrityError, transaction

        for sibling in self.batch_siblings:
            for name in self.BATCH_SHARED_FIELDS:
                setattr(sibling, name, getattr(report, name))
            same_times = before_times is not None and all(
                getattr(sibling, name) == before_times[name] for name in self.TIME_FIELDS
            )
            if same_times:
                for name in self.TIME_FIELDS:
                    setattr(sibling, name, getattr(report, name))
            try:
                with transaction.atomic():
                    sibling.save()
            except IntegrityError:
                self.propagate_skipped.append(sibling.worker)
                continue
            self.propagated.append(sibling)
