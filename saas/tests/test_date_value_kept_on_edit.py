"""編集画面で、前に登録した日付が消えないこと。

`<input type="date">` は `YYYY-MM-DD` しか値として受け取らない。テンプレート側で
`{{ form.start_date.value }}` と書くと、Django が日付を表示用の書式（ja なので
「2026年9月16日」）に直して埋めるため、ブラウザが値を捨てて**空欄**になる。
保存すると空のまま上書きされ、一度入れた工期が消える。

そのため日付欄はフォームのウィジェット（`{{ form.start_date }}`）で描くことにし、
テンプレートに手書きの `type="date"` を戻させないようにここで見張る。

日付欄は画面の状態で `BoundField.value()` の型が変わるので、3つの状態を固定する。

| 状態 | `.value` の型 | 期待 |
|---|---|---|
| 編集画面を開く | `datetime.date` | 登録済みの日付が `YYYY-MM-DD` で入る |
| 新規作成 | `None` | 空のまま（今日の日付などを勝手に入れない） |
| 入力エラーの描き直し | `str` | 打った日付がそのまま残る |

**3つ目を外さないこと。** 手書きに `|date:'Y-m-d'` を足す直し方でも編集画面は直るが、
このとき `.value` は送信された文字列で、`date` フィルタは文字列に空を返す。
他の欄でエラーが出るたびに打った日付が消えるため、その直し方はここで落ちる。
"""

import datetime
import re
from pathlib import Path

import pytest
from django.urls import reverse

from apps.devkanri.models import DevProject, DevTask
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

    def test_開発プロジェクトの日付が編集画面に入ったまま出る(self, client, company_a, user_a):
        project = DevProject.unscoped.create(
            company=company_a, name="業務管理システム",
            start_date=datetime.date(2026, 9, 16),
            due_date=datetime.date(2026, 12, 25),
        )
        client.force_login(user_a)
        body = client.get(
            reverse("devkanri:project_edit", args=[project.pk])
        ).content.decode()

        assert 'value="2026-09-16"' in body
        assert 'value="2026-12-25"' in body

    def test_開発タスクの期限が編集画面に入ったまま出る(self, client, company_a, user_a):
        project = DevProject.unscoped.create(company=company_a, name="業務管理システム")
        task = DevTask.unscoped.create(
            company=company_a, project=project, title="日付が消える不具合",
            due_date=datetime.date(2026, 12, 25),
        )
        client.force_login(user_a)
        body = client.get(reverse("devkanri:task_edit", args=[task.pk])).content.decode()

        assert 'value="2026-12-25"' in body


@pytest.mark.django_db
class TestCreateStaysEmpty:
    """新規作成では空のまま。ウィジェットに変えても初期値を持ち込まないこと。"""

    def test_現場の新規作成では工期が空(self, client, company_a, user_a):
        client.force_login(user_a)
        body = client.get(reverse("sites:create")).content.decode()

        assert 'name="start_date"' in body
        assert 'name="start_date" value=' not in body
        assert 'name="end_date" value=' not in body

    def test_工程フェーズの新規作成では日付が空(self, client, company_a, user_a):
        site = Site.unscoped.create(company=company_a, code="S010", name="D社事務所")
        client.force_login(user_a)
        body = client.get(
            reverse("schedules:phase_create", args=[site.pk])
        ).content.decode()

        assert 'name="start_date"' in body
        assert 'name="start_date" value=' not in body


@pytest.mark.django_db
class TestValidationErrorKeepsTypedDate:
    """入力エラーで描き直したとき、打った日付が残ること。

    `|date:'Y-m-d'` で直す案はここで落ちる（文字列に対して空を返すため）。
    """

    def test_現場名を空で送って戻っても打った日付が残る(self, client, company_a, user_a):
        site = Site.unscoped.create(
            company=company_a, code="S011", name="E社ビル",
            start_date=datetime.date(2026, 9, 16),
        )
        client.force_login(user_a)

        # name は必須。空で送るとエラーで同じ画面に戻る
        res = client.post(reverse("sites:edit", args=[site.pk]), {
            "code": "S011", "name": "", "status": Site.Status.IN_PROGRESS,
            "start_date": "2026-09-16", "end_date": "2026-12-25",
        })

        assert res.status_code == 200
        body = res.content.decode()
        assert 'value="2026-09-16"' in body
        assert 'value="2026-12-25"' in body

    def test_工程フェーズ名を空で送って戻っても打った日付が残る(
        self, client, company_a, user_a,
    ):
        site = Site.unscoped.create(company=company_a, code="S012", name="F社倉庫")
        phase = Phase.unscoped.create(
            company=company_a, site=site, name="仮設",
            start_date=datetime.date(2026, 9, 16),
        )
        client.force_login(user_a)

        res = client.post(reverse("schedules:phase_edit", args=[phase.pk]), {
            "name": "", "start_date": "2026-09-16", "end_date": "2026-10-01",
            "progress": "0", "sort_order": "0", "color": "#3b82f6", "memo": "",
        })

        assert res.status_code == 200
        body = res.content.decode()
        assert 'value="2026-09-16"' in body
        assert 'value="2026-10-01"' in body


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
