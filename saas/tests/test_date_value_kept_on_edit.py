"""編集画面で、前に登録した日付が消えないこと。

`<input type="date">` は `YYYY-MM-DD` しか値として受け取らない。テンプレート側で
`{{ form.start_date.value }}` と書くと、Django が日付を表示用の書式（ja なので
「2026年9月16日」）に直して埋めるため、ブラウザが値を捨てて**空欄**になる。
保存すると空のまま上書きされ、一度入れた工期が消える。

そのため日付欄はフォームのウィジェット（`{{ form.start_date }}`）で描くことにし、
テンプレートに手書きの `type="date"` を戻させないようにここで見張る。
"""

import datetime
import re
from pathlib import Path

import pytest
from django.urls import reverse

from apps.schedules.models import Milestone, Phase
from apps.sites.models import Site

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# 手書きの `<input type="date" ... value="{{ form.X.value }}">`。改行をまたぐので
# タグ全体を1つの塊として拾う。
HANDWRITTEN_DATE_INPUT = re.compile(r'<input[^>]*type="date"[^>]*>')


@pytest.mark.django_db
class TestDateKeptOnEdit:
    def test_現場の工期が編集画面に入ったまま出る(self, client, company_a, user_a):
        site = Site.unscoped.create(
            company=company_a, code="S001", name="A社ビル",
            start_date=datetime.date(2026, 9, 16),
            end_date=datetime.date(2026, 11, 30),
        )
        client.force_login(user_a)
        body = client.get(reverse("sites:edit", args=[site.pk])).content.decode()

        assert 'name="start_date"' in body
        assert 'value="2026-09-16"' in body
        assert 'value="2026-11-30"' in body
        assert "2026年9月16日" not in body

    def test_工程フェーズの日付が編集画面に入ったまま出る(self, client, company_a, user_a):
        site = Site.unscoped.create(company=company_a, code="S002", name="B社倉庫")
        phase = Phase.unscoped.create(
            company=company_a, site=site, name="仮設",
            start_date=datetime.date(2026, 9, 16),
            end_date=datetime.date(2026, 10, 1),
        )
        client.force_login(user_a)
        body = client.get(reverse("schedules:phase_edit", args=[phase.pk])).content.decode()

        assert 'value="2026-09-16"' in body
        assert 'value="2026-10-01"' in body

    def test_マイルストーンの目標日が編集画面に入ったまま出る(self, client, company_a, user_a):
        site = Site.unscoped.create(company=company_a, code="S003", name="C社工場")
        milestone = Milestone.unscoped.create(
            company=company_a, site=site, name="受電",
            target_date=datetime.date(2026, 12, 25),
        )
        client.force_login(user_a)
        body = client.get(
            reverse("schedules:milestone_edit", args=[milestone.pk])
        ).content.decode()

        assert 'value="2026-12-25"' in body


def test_日付欄を手書きのinputで描いているテンプレートが無い():
    offenders = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        for tag in HANDWRITTEN_DATE_INPUT.findall(path.read_text(encoding="utf-8")):
            # フォーム以外の日付欄（絞り込み条件など）はウィジェットを持たないので、
            # 見張るのは「フォームの値をそのまま埋めている」ものだけ。
            if re.search(r"\{\{\s*form\.\w+\.value", tag):
                offenders.append(f"{path.relative_to(TEMPLATES_DIR)}: {tag}")
    assert not offenders, (
        "日付欄は {{ form.フィールド名 }} で描いてください"
        "（手書きの value では ja の表示書式になり空欄になります）:\n"
        + "\n".join(offenders)
    )
