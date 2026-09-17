"""現場名を指定して二重登録をまとめるコマンド（ADR-0090）。

確かめること:

1. --apply を付けるまで書き込まない
2. 付けると、画面と同じ道筋（merge_sites）で記録が付け替わる
3. 3つ以上を1回でまとめ、最後に名前を揃えられる
4. 取り消せる（候補の行に付け替えた記録が残る）
5. 見つからない・2つある・統合済み・自分自身 は止める
"""
import datetime
import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.merge import undo_merge
from apps.sites.models import Site, SiteMergeCandidate
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)


def _site(company, code, name, **kwargs):
    return Site.unscoped.create(company=company, code=code, name=name, **kwargs)


def _run(*, keep, merge, rename="", company="", apply=False):
    """本物のコマンドラインと同じ形で流す（--merge の繰り返しを含めて確かめるため）。"""
    args = ["--keep", keep]
    for name in merge:
        args += ["--merge", name]
    if rename:
        args += ["--rename", rename]
    if company:
        args += ["--company", company]
    if apply:
        args.append("--apply")
    out = io.StringIO()
    call_command("merge_sites_by_name", *args, stdout=out, stderr=out)
    return out.getvalue()


@pytest.fixture
def festival(company_a):
    return {
        "atsugi_ayu": _site(company_a, "S101", "厚木あゆ祭り"),
        "ayu": _site(company_a, "S102", "あゆ祭り"),
        "atsugi_matsuri": _site(company_a, "S103", "厚木鮎まつり"),
    }


@pytest.fixture
def report_setup(company_a):
    work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
    worker = Worker.unscoped.create(company=company_a, name="電工太郎")
    return work_type, worker


def _report(company, site, setup, day=DAY):
    work_type, worker = setup
    return DailyReport.unscoped.create(
        company=company, site=site, work_type=work_type, worker=worker,
        report_date=day, work_hours=8,
    )


@pytest.mark.django_db
class TestDryRun:
    def test_applyを付けないと書き込まない(self, company_a, festival, report_setup):
        _report(company_a, festival["ayu"], report_setup)

        out = _run(keep="厚木あゆ祭り", merge=["あゆ祭り"])

        festival["ayu"].refresh_from_db()
        assert festival["ayu"].merged_into_id is None
        assert DailyReport.unscoped.get(company=company_a).site_id == festival["ayu"].pk
        assert "何も書き込んでいません" in out

    def test_確認では記録の件数を出す(self, company_a, festival, report_setup):
        _report(company_a, festival["ayu"], report_setup)

        out = _run(keep="厚木あゆ祭り", merge=["あゆ祭り"])

        assert "厚木あゆ祭り" in out
        assert "あゆ祭り（記録 1 件）" in out


@pytest.mark.django_db
class TestApply:
    def test_記録が残すほうへ移る(self, company_a, festival, report_setup):
        _report(company_a, festival["ayu"], report_setup)

        _run(keep="厚木あゆ祭り", merge=["あゆ祭り"], apply=True)

        festival["ayu"].refresh_from_db()
        assert festival["ayu"].merged_into_id == festival["atsugi_ayu"].pk
        assert DailyReport.unscoped.get(company=company_a).site_id == festival["atsugi_ayu"].pk

    def test_3つを1回でまとめて名前を揃えられる(self, company_a, festival, report_setup):
        _report(company_a, festival["ayu"], report_setup)
        _report(
            company_a, festival["atsugi_matsuri"], report_setup,
            day=DAY + datetime.timedelta(days=1),
        )

        _run(
            keep="厚木あゆ祭り", merge=["あゆ祭り", "厚木鮎まつり"],
            rename="厚木鮎祭り", apply=True,
        )

        keep = festival["atsugi_ayu"]
        keep.refresh_from_db()
        assert keep.name == "厚木鮎祭り"
        assert DailyReport.unscoped.filter(company=company_a, site=keep).count() == 2
        assert Site.unscoped.filter(company=company_a, merged_into=keep).count() == 2

    def test_統合済みは現場一覧に出ない(self, client, company_a, user_a, festival):
        _run(keep="厚木あゆ祭り", merge=["あゆ祭り"], apply=True)
        client.force_login(user_a)

        html = client.get("/sites/").content.decode()

        assert "厚木鮎まつり" in html
        assert "あゆ祭り</" not in html.replace("厚木あゆ祭り</", "")

    def test_コマンドで統合しても取り消せる(self, company_a, festival, report_setup):
        _report(company_a, festival["ayu"], report_setup)

        _run(keep="厚木あゆ祭り", merge=["あゆ祭り"], apply=True)
        candidate = SiteMergeCandidate.unscoped.get(company=company_a)
        undo_merge(candidate)

        festival["ayu"].refresh_from_db()
        assert festival["ayu"].merged_into_id is None
        assert DailyReport.unscoped.get(company=company_a).site_id == festival["ayu"].pk


@pytest.mark.django_db
class TestValidation:
    def test_現場が見つからなければ止める(self, company_a, festival):
        with pytest.raises(CommandError, match="現場が見つかりません"):
            _run(keep="厚木あゆ祭り", merge=["無い現場"])

    def test_同じ名前が2つあれば止める(self, company_a, festival):
        _site(company_a, "S104", "あゆ祭り")

        with pytest.raises(CommandError, match="2つ以上あります"):
            _run(keep="厚木あゆ祭り", merge=["あゆ祭り"])

    def test_統合済みの現場は止める(self, company_a, festival):
        _run(keep="厚木あゆ祭り", merge=["あゆ祭り"], apply=True)

        with pytest.raises(CommandError, match="既に"):
            _run(keep="厚木鮎まつり", merge=["あゆ祭り"], apply=True)

    def test_自分自身にはまとめられない(self, company_a, festival):
        with pytest.raises(CommandError, match="自分自身"):
            _run(keep="厚木あゆ祭り", merge=["厚木あゆ祭り"], apply=True)

    def test_会社が複数あれば会社名を求める(self, company_a, company_b, festival):
        with pytest.raises(CommandError, match="--company"):
            _run(keep="厚木あゆ祭り", merge=["あゆ祭り"])


@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の同名の現場には触れない(self, company_a, company_b, festival, report_setup):
        other_keep = _site(company_b, "B001", "厚木あゆ祭り")
        other_drop = _site(company_b, "B002", "あゆ祭り")

        _run(keep="厚木あゆ祭り", merge=["あゆ祭り"], company=company_a.name, apply=True)

        other_drop.refresh_from_db()
        assert other_drop.merged_into_id is None
        assert other_keep.name == "厚木あゆ祭り"
