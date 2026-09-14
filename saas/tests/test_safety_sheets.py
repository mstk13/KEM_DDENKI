"""現場の安全書類（KY用紙・安全作業確認書）と朝の知らせ（ADR-0061）。

ここで固定すること:
1. KY用紙は現場ごと1日1枚。上半分は作業責任者が書き、危険の行と SC-5 の確認はまとめて持つ。
   前の用紙から作業内容と危険の行を写す（危険度と確認は写さない）
2. 参加者は自分の行（サイン・健康状態・検電器）を書く。同じ人は上書き。不調なら症状が要る。
   サインは PNG でないと受け付けない。他社の作業員は選べない
3. 安全作業確認書は現場ごとに1人1回。作業員の登録と最新の健康診断から最初の値を入れる。
   見て書けるのは管理者・事務員・Developer・社長・本人だけ
4. PDF に記入した内容が出る（KY用紙は20人を超えたら次の用紙に続く）
5. 朝の知らせは、その日その現場に出る人（アカウントのある人）に1回だけ。
   安全作業確認書がまだの人にはそれも書く
6. 記録は会社ごとに分かれ、変更履歴と管理画面がある
"""

import base64
import datetime
import io

import pdfplumber
import pytest
from django.contrib import admin
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.attendance.models import AttendPlan
from apps.core.tenant_context import set_current_company
from apps.notifications.models import Notification
from apps.safety.formats import RISK_ROWS, SC5_ROWS
from apps.safety.models import EntryConfirmation, KyParticipant, KySheet
from apps.safety.pdf import generate_entry_pdf, generate_ky_pdf
from apps.safety.services import (
    experience_years_months,
    ky_initial,
    send_morning_reminders,
)
from apps.sites.models import Site
from apps.workers.models import HealthCheckup, Position, Worker

DAY = datetime.date(2026, 9, 15)


def _signature(width=120, height=40):
    buffer = io.BytesIO()
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    for x in range(10, width - 10):
        image.putpixel((x, height // 2), (0, 0, 0, 255))
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@pytest.fixture
def site(company_a):
    return Site.unscoped.create(
        company=company_a,
        code="S001",
        name="A社ビル新築",
        status=Site.Status.IN_PROGRESS,
    )


def _worker(company, name, code, position="正社員", user=None, **extra):
    pos = Position.unscoped.get_or_create(company=company, name=position)[0]
    return Worker.unscoped.create(
        company=company,
        name=name,
        employee_code=code,
        position=pos,
        user=user,
        **extra,
    )


def _user_worker(django_user_model, company, username, code, position="正社員", **extra):
    user = django_user_model.objects.create_user(
        username=username,
        password="testpass123",
        company=company,
    )
    return user, _worker(company, f"{username}さん", code, position, user=user, **extra)


def _plan(worker, site, day=DAY, kind="site"):
    return AttendPlan.unscoped.create(
        company=worker.company,
        worker=worker,
        plan_date=day,
        kind=kind,
        note=site.name,
    )


def _ky_post(**extra):
    data = {
        "crew_name": "電気班",
        "planned_headcount": "3",
        "work_start": "08:00",
        "work_end": "17:30",
        "leader_name": "江頭 敏幸",
        "work_content": "2F 分電盤の更新",
        "safety_instructions": "停電の確認を必ず行う",
        "extra_check_7": "",
        "extra_check_8": "",
        "sc5_extra_5": "",
        "sc5_extra_6": "",
        "remarks": "",
    }
    for i in range(RISK_ROWS):
        data.update({f"risk_hazard_{i}": "", f"risk_level_{i}": "", f"risk_measure_{i}": ""})
    data.update(extra)
    return data


def _sign_post(worker, **extra):
    data = {
        "worker": worker.pk,
        "health": "good",
        "health_note": "",
        "tester": "carrying",
        "signature": _signature(),
    }
    data.update(extra)
    return data


def _pdf_text(content):
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages), len(pdf.pages)


def _sheet(site, day=DAY, **extra):
    return KySheet.unscoped.create(company=site.company, site=site, work_date=day, **extra)


# ---------------------------------------------------------------------------
# モデル
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModels:
    def test_他社の安全書類は見えない(self, company_a, company_b, site):
        other_site = Site.unscoped.create(company=company_b, code="S001", name="B社現場")
        mine = _sheet(site)
        other = _sheet(other_site)
        worker = _worker(company_a, "田中", "E001")
        other_worker = _worker(company_b, "佐藤", "E001")
        KyParticipant.unscoped.create(
            company=company_a,
            sheet=mine,
            worker=worker,
            tester="carrying",
            signature=_signature(),
        )
        KyParticipant.unscoped.create(
            company=company_b,
            sheet=other,
            worker=other_worker,
            tester="carrying",
            signature=_signature(),
        )
        EntryConfirmation.unscoped.create(
            company=company_a, site=site, worker=worker, entry_date=DAY
        )
        EntryConfirmation.unscoped.create(
            company=company_b,
            site=other_site,
            worker=other_worker,
            entry_date=DAY,
        )

        set_current_company(company_a)
        try:
            assert list(KySheet.objects.all()) == [mine]
            assert KyParticipant.objects.count() == 1
            assert EntryConfirmation.objects.get().worker == worker
        finally:
            set_current_company(None)

    def test_同じ現場_同じ日のKY用紙は1枚(self, site):
        _sheet(site)

        with pytest.raises(IntegrityError), transaction.atomic():
            _sheet(site)

    def test_変更履歴が残り管理画面に出る(self, company_a, site):
        sheet = _sheet(site)
        worker = _worker(company_a, "田中", "E001")
        KyParticipant.unscoped.create(
            company=company_a,
            sheet=sheet,
            worker=worker,
            tester="carrying",
            signature=_signature(),
        )
        EntryConfirmation.unscoped.create(
            company=company_a, site=site, worker=worker, entry_date=DAY
        )

        assert KySheet.history.count() == 1
        assert KyParticipant.history.count() == 1
        assert EntryConfirmation.history.count() == 1
        for model in (KySheet, KyParticipant, EntryConfirmation):
            assert admin.site.is_registered(model)


# ---------------------------------------------------------------------------
# KY用紙
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestKyInitial:
    def test_前の用紙が無ければ様式の既定値(self, site):
        initial = ky_initial(site, DAY)

        assert initial["work_start"] == datetime.time(8, 0)
        assert initial["work_end"] == datetime.time(17, 30)
        assert [row["hazard"] for row in initial["risks"]][:4] == [
            "感電",
            "転倒",
            "墜落",
            "物の落下",
        ]
        assert len(initial["risks"]) == RISK_ROWS
        assert all(row["level"] == "" and not row["checked"] for row in initial["risks"])

    def test_前の用紙から作業内容と危険の行を写し_危険度と確認は写さない(self, site):
        _sheet(
            site,
            day=DAY - datetime.timedelta(days=3),
            crew_name="電気班",
            work_content="幹線ケーブル敷設",
            risks=[{"hazard": "挟まれ", "level": "大", "measure": "合図の徹底", "checked": True}],
        )

        initial = ky_initial(site, DAY)

        assert initial["crew_name"] == "電気班"
        assert initial["work_content"] == "幹線ケーブル敷設"
        assert initial["risks"] == [
            {"hazard": "挟まれ", "level": "", "measure": "合図の徹底", "checked": False},
        ]

    def test_予定人数はその日の参加者の数(self, company_a, site):
        for i in range(2):
            _plan(_worker(company_a, f"作業員{i}", f"E00{i}"), site)
        _plan(_worker(company_a, "休み", "E009"), site, kind="off")

        assert ky_initial(site, DAY)["planned_headcount"] == 2


@pytest.mark.django_db
class TestKySheetViews:
    def _url(self, site, day=DAY):
        return reverse("safety:ky_sheet", kwargs={"site_pk": site.pk, "day": day})

    def test_開くと最初の値が入った画面が出る(self, client, user_a, site):
        client.force_login(user_a)

        res = client.get(self._url(site))

        assert res.status_code == 200
        body = res.content.decode()
        assert "感電" in body
        assert "data-offline-form" in body
        assert not KySheet.unscoped.exists()

    def test_保存すると危険の行とSC5の確認をまとめて持つ(self, client, user_a, site):
        client.force_login(user_a)

        res = client.post(
            self._url(site),
            _ky_post(
                risk_hazard_0="感電",
                risk_level_0="大",
                risk_measure_0="活線作業の禁止",
                risk_checked_0="on",
                sc5_check_1="on",
            ),
        )

        assert res.status_code == 302
        sheet = KySheet.unscoped.get(site=site, work_date=DAY)
        assert sheet.crew_name == "電気班"
        assert sheet.risks[0] == {
            "hazard": "感電",
            "level": "大",
            "measure": "活線作業の禁止",
            "checked": True,
        }
        assert len(sheet.risks) == RISK_ROWS
        assert sheet.sc5_checks == [False, True] + [False] * (SC5_ROWS - 2)

    def test_日付として無いURLは404(self, client, user_a, site):
        client.force_login(user_a)

        assert client.get(f"/safety/sites/{site.pk}/ky/2026-13-40/").status_code == 404

    def test_他社の現場は開けない(self, client, user_b, site):
        client.force_login(user_b)

        assert client.get(self._url(site)).status_code == 404


@pytest.mark.django_db
class TestKySign:
    def _url(self, site, day=DAY):
        return reverse("safety:ky_sign", kwargs={"site_pk": site.pk, "day": day})

    def test_自分の行を書くと用紙ができて行が入る(
        self, client, django_user_model, company_a, site
    ):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        client.force_login(user)

        form = client.get(self._url(site)).context["form"]
        res = client.post(self._url(site), _sign_post(me))

        assert form.initial["worker"] == me
        assert res.status_code == 302
        participant = KyParticipant.unscoped.get(sheet__site=site, sheet__work_date=DAY)
        assert participant.worker == me
        assert (participant.health_mark, participant.tester_mark) == ("○", "○")
        assert KySheet.unscoped.get().risks[0]["hazard"] == "感電"

    def test_同じ人が書き直すと行を上書きする(self, client, django_user_model, company_a, site):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        client.force_login(user)

        client.post(self._url(site), _sign_post(me))
        client.post(self._url(site), _sign_post(me, tester="not_needed"))

        participant = KyParticipant.unscoped.get()
        assert participant.tester_mark == "－"

    def test_不調なら症状が要る(self, client, user_a, company_a, site):
        worker = _worker(company_a, "田中", "E001")
        client.force_login(user_a)

        res = client.post(self._url(site), _sign_post(worker, health="poor"))

        assert "health_note" in res.context["form"].errors
        assert not KyParticipant.unscoped.exists()

    @pytest.mark.parametrize(
        "signature", ["", "data:image/png;base64,AAAA", "data:image/jpeg;base64,/9j/"]
    )
    def test_サインが無い_PNGでないと受け付けない(
        self, client, user_a, company_a, site, signature
    ):
        worker = _worker(company_a, "田中", "E001")
        client.force_login(user_a)

        res = client.post(self._url(site), _sign_post(worker, signature=signature))

        assert "signature" in res.context["form"].errors
        assert not KyParticipant.unscoped.exists()

    def test_他社の作業員は選べない(self, client, user_a, company_b, site):
        other = _worker(company_b, "佐藤", "E001")
        client.force_login(user_a)

        res = client.post(self._url(site), _sign_post(other))

        assert "worker" in res.context["form"].errors


@pytest.mark.django_db
class TestKySignoff:
    def test_指導事項の文とサインを書ける(self, client, user_a, site):
        sheet = _sheet(site)
        client.force_login(user_a)

        res = client.post(
            reverse("safety:ky_signoff", kwargs={"pk": sheet.pk, "kind": "guidance"}),
            {"text": "高所作業は2人で行う", "signature": _signature()},
        )

        assert res.status_code == 302
        sheet.refresh_from_db()
        assert sheet.guidance == "高所作業は2人で行う"
        assert sheet.guidance_signature.startswith("data:image/png;base64,")

    def test_知らない欄は404(self, client, user_a, site):
        sheet = _sheet(site)
        client.force_login(user_a)

        url = reverse("safety:ky_signoff", kwargs={"pk": sheet.pk, "kind": "unknown"})
        assert client.get(url).status_code == 404


# ---------------------------------------------------------------------------
# 安全作業確認書
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEntryConfirmation:
    def _create_url(self, site, worker=None):
        url = reverse("safety:entry_create", kwargs={"site_pk": site.pk})
        return f"{url}?worker={worker.pk}" if worker else url

    def test_本人は書け_登録内容と最新の健康診断が最初から入る(
        self,
        client,
        django_user_model,
        company_a,
        site,
    ):
        started = datetime.date(2015, 4, 1)
        user, me = _user_worker(
            django_user_model,
            company_a,
            "e010",
            "E010",
            postal_code="123-4567",
            address="東京都千代田区1-2-3",
            phone="090-1111-2222",
            emergency_contact_name="田中花子",
            emergency_contact_relationship="妻",
            blood_type="A",
            experience_started_on=started,
        )
        HealthCheckup.unscoped.create(
            company=company_a,
            worker=me,
            checkup_date=datetime.date(2026, 4, 1),
            vision_right_naked=1.0,
            vision_right_corrected=1.2,
            vision_left_naked=0.8,
            blood_pressure_high=128,
            blood_pressure_low=82,
        )
        client.force_login(user)

        initial = client.get(self._create_url(site)).context["form"].initial

        assert initial["address"] == "〒123-4567 東京都千代田区1-2-3"
        assert initial["emergency_contact_name"] == "田中花子（妻）"
        assert initial["blood_type"] == "A"
        assert initial["vision_right"] == "1.2"  # 矯正があれば矯正
        assert initial["vision_left"] == "0.8"
        assert (initial["blood_pressure_high"], initial["blood_pressure_low"]) == (128, 82)
        assert (
            initial["experience_years"]
            == experience_years_months(started, timezone.localdate())[0]
        )

    def test_登録すると1回だけで_2回目は直す画面へ(
        self, client, django_user_model, company_a, site
    ):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        client.force_login(user)
        data = {
            "entry_date": "2026-09-15",
            "address": "東京都港区",
            "shock_education": "True",
            "business_type": "neither",
            "signature": _signature(),
        }

        res = client.post(self._create_url(site), data)
        again = client.get(self._create_url(site))

        confirmation = EntryConfirmation.unscoped.get()
        assert res["Location"] == reverse("safety:entry_detail", kwargs={"pk": confirmation.pk})
        assert confirmation.shock_education is True
        assert confirmation.business_type == "neither"
        assert again["Location"] == reverse("safety:entry_edit", kwargs={"pk": confirmation.pk})

    def test_役割の無い人は他の人の確認書を見られない(self, client, user_a, company_a, site):
        worker = _worker(company_a, "田中", "E001")
        confirmation = EntryConfirmation.unscoped.create(
            company=company_a,
            site=site,
            worker=worker,
            entry_date=DAY,
            address="秘密の住所",
        )
        client.force_login(user_a)

        assert client.get(self._create_url(site, worker)).status_code == 403
        for name in ("safety:entry_detail", "safety:entry_edit", "safety:entry_pdf"):
            assert client.get(reverse(name, kwargs={"pk": confirmation.pk})).status_code == 403, (
                name
            )
        body = client.get(reverse("safety:site", kwargs={"site_pk": site.pk})).content.decode()
        assert "管理者・事務員・本人のみ" in body

    def test_管理者は他の人の確認書を書ける(self, client, django_user_model, company_a, site):
        admin_user, _me = _user_worker(django_user_model, company_a, "y001", "Y001", "社長")
        worker = _worker(company_a, "田中", "E001")
        client.force_login(admin_user)

        assert client.get(self._create_url(site, worker)).status_code == 200

    def test_経験年数を年と月で出す(self):
        assert experience_years_months(datetime.date(2020, 4, 10), DAY) == (6, 5)
        assert experience_years_months(datetime.date(2020, 4, 16), DAY) == (6, 4)
        assert experience_years_months(None, DAY) == (None, None)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPdf:
    def test_KY用紙のPDFに記入した内容と参加者が出る(self, client, user_a, company_a, site):
        sheet = _sheet(
            site,
            crew_name="電気班",
            work_content="2F 分電盤の更新",
            remarks="雨天",
            risks=[
                {"hazard": "感電", "level": "大", "measure": "活線作業の禁止", "checked": True}
            ],
            sc5_checks=[True] * SC5_ROWS,
        )
        worker = _worker(company_a, "田中", "E001")
        KyParticipant.unscoped.create(
            company=company_a,
            sheet=sheet,
            worker=worker,
            tester="carrying",
            signature=_signature(),
        )
        client.force_login(user_a)

        res = client.get(reverse("safety:ky_pdf", kwargs={"pk": sheet.pk}))

        assert res.status_code == 200
        assert res["Content-Type"] == "application/pdf"
        text, pages = _pdf_text(res.content)
        assert pages == 1
        for expected in (
            "A社ビル新築",
            "電気班",
            "2F 分電盤の更新",
            "活線作業の禁止",
            "作業場所と作業内容",
            "1 人",
        ):
            assert expected in text, expected

    def test_参加者が20人を超えたら次の用紙に続く(self, company_a, site):
        sheet = _sheet(site)
        for i in range(21):
            KyParticipant.unscoped.create(
                company=company_a,
                sheet=sheet,
                worker=_worker(company_a, f"作業員{i}", f"E{i:03d}"),
                tester="carrying",
                signature="",
            )

        _text, pages = _pdf_text(generate_ky_pdf(sheet))

        assert pages == 2

    def test_安全作業確認書のPDFに本人の値と心得が出る(self, company_a, site):
        worker = _worker(company_a, "田中太郎", "E001")
        confirmation = EntryConfirmation.unscoped.create(
            company=company_a,
            site=site,
            worker=worker,
            entry_date=DAY,
            address="東京都千代田区1-2-3",
            emergency_contact_name="田中花子（妻）",
            blood_type="O",
            shock_education=True,
            business_type="neither",
            paying_company="株式会社サンプル",
            signature=_signature(),
        )

        text, pages = _pdf_text(generate_entry_pdf(confirmation))

        assert pages == 1
        for expected in (
            "A社ビル新築",
            "田中太郎",
            "東京都千代田区1-2-3",
            "田中花子（妻）",
            "O型",
            "株式会社サンプル",
            "私は事故を絶対に起こしません",
            "感電災害事故防止",
        ):
            assert expected in text, expected


# ---------------------------------------------------------------------------
# 現場の画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSitePages:
    def test_現場詳細に安全書類の欄がある(self, client, user_a, site):
        client.force_login(user_a)

        body = client.get(reverse("sites:detail", args=[site.pk])).content.decode()

        assert "安全書類（KY用紙・安全作業確認書）" in body
        assert reverse("safety:site", kwargs={"site_pk": site.pk}) in body

    def test_安全書類の画面に今日の参加者とまだの人が出る(self, client, user_a, company_a, site):
        worker = _worker(company_a, "田中太郎", "E001")
        _plan(worker, site, day=timezone.localdate())
        client.force_login(user_a)

        body = client.get(reverse("safety:site", kwargs={"site_pk": site.pk})).content.decode()

        assert "田中太郎 まだ" in body

    def test_別の日を選ぶとその日のKY用紙へ(self, client, user_a, site):
        client.force_login(user_a)

        res = client.get(
            reverse("safety:site", kwargs={"site_pk": site.pk}), {"day": "2026-09-15"}
        )

        assert res["Location"] == reverse(
            "safety:ky_sheet", kwargs={"site_pk": site.pk, "day": DAY}
        )


# ---------------------------------------------------------------------------
# 朝の知らせ
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMorningReminders:
    def test_その日に現場へ出る人に知らせ_確認書がまだならそれも書く(
        self,
        django_user_model,
        company_a,
        site,
    ):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        _plan(me, site)

        created = send_morning_reminders(company_a, DAY)

        assert created == 1
        notification = Notification.unscoped.get(recipient=user)
        assert "A社ビル新築" in notification.title
        assert notification.module == Notification.Module.SAFETY
        assert notification.reference_url == reverse(
            "safety:ky_sheet",
            kwargs={"site_pk": site.pk, "day": DAY},
        )
        assert "安全作業確認書がまだ" in notification.body

    def test_同じ日に2回走っても重ねない(self, django_user_model, company_a, site):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        _plan(me, site)

        send_morning_reminders(company_a, DAY)
        send_morning_reminders(company_a, DAY)

        assert Notification.unscoped.filter(recipient=user).count() == 1

    def test_確認書を書いてある人には確認書の文を出さない(
        self, django_user_model, company_a, site
    ):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        _plan(me, site)
        EntryConfirmation.unscoped.create(company=company_a, site=site, worker=me, entry_date=DAY)

        send_morning_reminders(company_a, DAY)

        assert "安全作業確認書" not in Notification.unscoped.get(recipient=user).body

    def test_アカウントの無い人_休みの人_完工の現場には出さない(
        self,
        django_user_model,
        company_a,
        site,
    ):
        _plan(_worker(company_a, "アカウントなし", "E001"), site)
        _user, off_worker = _user_worker(django_user_model, company_a, "e011", "E011")
        _plan(off_worker, site, kind="off")
        done = Site.unscoped.create(
            company=company_a,
            code="S009",
            name="完工した現場",
            status=Site.Status.COMPLETED,
        )
        _user2, done_worker = _user_worker(django_user_model, company_a, "e012", "E012")
        _plan(done_worker, done)

        assert send_morning_reminders(company_a, DAY) == 0
        assert not Notification.unscoped.exists()

    def test_コマンドで知らせる(self, django_user_model, company_a, site):
        user, me = _user_worker(django_user_model, company_a, "e010", "E010")
        _plan(me, site)

        call_command("send_safety_reminders", date="2026-09-15", stdout=io.StringIO())

        assert Notification.unscoped.filter(recipient=user).count() == 1
