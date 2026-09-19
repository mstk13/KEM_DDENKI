"""評価項目とアンケート設問の書き出し・読み込み（ADR-0102）。

- 書き出したファイルを別の会社（＝別の環境のかわり）で読み込むと、同じ内容になる
- 読み込みは足すか直すだけ。ファイルに無い項目は消さない
- 確認だけのときは保存しない
"""

import json

import pytest
from django.urls import reverse

from apps.evaluation.models import EvalItem, SurveyQuestion
from apps.evaluation.transfer import (
    BadFile,
    export_items,
    import_items,
    load_payload,
)


def _item(company, section="共通", num=1, name="報連相", **kwargs):
    return EvalItem.unscoped.create(
        company=company, section=section, num=num, name=name, **kwargs,
    )


def _question(company, item, qnum="1-1", text="連絡は早いか", order=1):
    return SurveyQuestion.unscoped.create(
        company=company, item=item, qnum=qnum, text=text, sort_order=order,
    )


@pytest.mark.django_db
class TestExport:
    def test_項目と設問を書き出す(self, company_a):
        item = _item(company_a, name="報連相", description="説明", max_score=5)
        _question(company_a, item, "1-1", "連絡は早いか")
        _question(company_a, item, "1-2", "報告は正しいか", order=2)

        payload = export_items(company_a, EvalItem)

        assert payload["format"] == "kem-eval-items"
        assert len(payload["items"]) == 1
        written = payload["items"][0]
        assert written["name"] == "報連相"
        assert [q["qnum"] for q in written["questions"]] == ["1-1", "1-2"]

    def test_他社の項目は書き出さない(self, company_a, company_b):
        _item(company_a, name="自社の項目")
        _item(company_b, name="他社の項目")

        payload = export_items(company_a, EvalItem)

        assert [i["name"] for i in payload["items"]] == ["自社の項目"]


@pytest.mark.django_db
class TestImport:
    def test_書き出した内容をそのまま入れられる(self, company_a, company_b):
        item = _item(company_a, name="報連相")
        _question(company_a, item, "1-1", "連絡は早いか")
        payload = export_items(company_a, EvalItem)

        report = import_items(company_b, EvalItem, SurveyQuestion, payload["items"])

        copied = EvalItem.unscoped.get(company=company_b)
        assert copied.name == "報連相"
        assert copied.questions.count() == 1
        assert len(report["created"]) == 1
        assert report["questions_created"] == 1

    def test_同じ項目は直す(self, company_a):
        _item(company_a, name="報連相", description="古い説明")
        items = [{
            "section": "共通", "num": 1, "name": "報連相",
            "description": "新しい説明", "questions": [],
        }]

        report = import_items(company_a, EvalItem, SurveyQuestion, items)

        assert EvalItem.unscoped.get().description == "新しい説明"
        assert len(report["updated"]) == 1
        assert EvalItem.unscoped.count() == 1

    def test_ファイルに無い項目は消さない(self, company_a):
        _item(company_a, num=1, name="残る項目")
        items = [{"section": "共通", "num": 2, "name": "足す項目", "questions": []}]

        import_items(company_a, EvalItem, SurveyQuestion, items)

        assert EvalItem.unscoped.filter(name="残る項目").exists()
        assert EvalItem.unscoped.count() == 2

    def test_設問も足して直す(self, company_a):
        item = _item(company_a)
        _question(company_a, item, "1-1", "古い質問")
        items = [{
            "section": "共通", "num": 1, "name": "報連相",
            "questions": [
                {"qnum": "1-1", "text": "新しい質問", "sort_order": 1},
                {"qnum": "1-2", "text": "足す質問", "sort_order": 2},
            ],
        }]

        report = import_items(company_a, EvalItem, SurveyQuestion, items)

        assert SurveyQuestion.unscoped.get(qnum="1-1").text == "新しい質問"
        assert SurveyQuestion.unscoped.filter(qnum="1-2").exists()
        assert report["questions_updated"] == 1
        assert report["questions_created"] == 1

    def test_確認だけなら保存しない(self, company_a, company_b):
        item = _item(company_a, name="報連相")
        _question(company_a, item, "1-1", "連絡は早いか")
        payload = export_items(company_a, EvalItem)

        report = import_items(
            company_b, EvalItem, SurveyQuestion, payload["items"], apply=False,
        )

        assert not EvalItem.unscoped.filter(company=company_b).exists()
        assert len(report["created"]) == 1
        assert report["questions_created"] == 1

    def test_形の違うファイルは断る(self):
        with pytest.raises(BadFile):
            load_payload('{"format": "別のもの", "items": []}')
        with pytest.raises(BadFile):
            load_payload("これはJSONではありません")

    def test_テンプレートのファイルなら行き先を教える(self):
        """実際に取り違えが起きたので、どっちの画面か書く（2026-09-19）。"""
        with pytest.raises(BadFile, match="評価テンプレートの編集"):
            load_payload('{"format": "kem-eval-template", "sections": []}')


@pytest.fixture
def officer(company_a, user_a):
    """人事評価の画面は役員・社長・Developer だけが使える。"""
    from apps.workers.models import Position, Worker

    position = Position.unscoped.create(company=company_a, name="役員")
    Worker.unscoped.create(
        company=company_a, name="役員 太郎", position=position, user=user_a,
    )
    return user_a


@pytest.mark.django_db
class TestScreen:
    def test_書き出しを押すとJSONが落ちてくる(self, client, company_a, officer):
        item = _item(company_a, name="報連相")
        _question(company_a, item, "1-1", "連絡は早いか")
        client.force_login(officer)

        res = client.get(reverse("evaluation:criteria_export"))

        assert res.status_code == 200
        assert "attachment" in res["Content-Disposition"]
        payload = json.loads(res.content.decode())
        assert payload["items"][0]["name"] == "報連相"

    def test_読み込むと画面に結果が出る(self, client, company_a, officer):
        from django.core.files.uploadedfile import SimpleUploadedFile

        client.force_login(officer)
        body = json.dumps({
            "format": "kem-eval-items", "version": 1,
            "items": [{"section": "共通", "num": 1, "name": "報連相", "questions": []}],
        }, ensure_ascii=False).encode()

        res = client.post(reverse("evaluation:criteria_import"), {
            "payload": SimpleUploadedFile(
                "eval_items.json", body, content_type="application/json",
            ),
            "apply": "1",
        }, follow=True)

        assert EvalItem.unscoped.filter(company=company_a, name="報連相").exists()
        assert "読み込みました" in res.content.decode()

    def test_確認だけでは登録しない(self, client, company_a, officer):
        from django.core.files.uploadedfile import SimpleUploadedFile

        client.force_login(officer)
        body = json.dumps({
            "format": "kem-eval-items", "version": 1,
            "items": [{"section": "共通", "num": 1, "name": "報連相", "questions": []}],
        }, ensure_ascii=False).encode()

        res = client.post(reverse("evaluation:criteria_import"), {
            "payload": SimpleUploadedFile(
                "eval_items.json", body, content_type="application/json",
            ),
        }, follow=True)

        assert not EvalItem.unscoped.exists()
        assert "こうなります" in res.content.decode()

    def test_ファイルを選ばずに押しても落ちない(self, client, officer):
        client.force_login(officer)

        res = client.post(reverse("evaluation:criteria_import"), follow=True)

        assert "ファイルが選ばれていません" in res.content.decode()


@pytest.mark.django_db
class TestTemplateTransfer:
    """人材評価のテンプレートの書き出し・読み込み（ADR-0102）。"""

    @pytest.fixture
    def admin_user(self, company_a, user_a):
        from django.contrib.auth.models import Group

        group, _created = Group.objects.get_or_create(name="admin")
        user_a.groups.add(group)
        return user_a

    @pytest.fixture
    def template(self, company_a):
        from apps.workers.models import EvaluationTemplate

        return EvaluationTemplate.unscoped.create(
            company=company_a, name="人材評価",
            sections=[{"section": "共通", "num": 1, "name": "報連相"}],
            survey_items=[{"section": "共通", "num": 1, "questions": [{"qnum": "1-1"}]}],
            scale=[{"value": 5, "label": "とても良い"}],
            overall=[{"qnum": "総1", "text": "良かった点"}],
        )

    def test_書き出すとテンプレートが落ちてくる(self, client, admin_user, template):
        client.force_login(admin_user)

        res = client.get(reverse("workers:eval_template_export"))

        assert res.status_code == 200
        payload = json.loads(res.content.decode())
        assert payload["format"] == "kem-eval-template"
        assert payload["sections"][0]["name"] == "報連相"
        assert payload["scale"][0]["label"] == "とても良い"

    def test_読み込むと中身が入れ替わる(self, client, admin_user, template):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.workers.models import EvaluationTemplate

        client.force_login(admin_user)
        body = json.dumps({
            "format": "kem-eval-template", "version": 1, "name": "人材評価",
            "sections": [{"section": "共通", "num": 1, "name": "直した項目"}],
            "survey_items": [], "scale": [], "overall": [],
        }, ensure_ascii=False).encode()

        res = client.post(reverse("workers:eval_template_import"), {
            "payload": SimpleUploadedFile(
                "eval_template.json", body, content_type="application/json",
            ),
            "apply": "1",
        }, follow=True)

        template.refresh_from_db()
        assert template.sections[0]["name"] == "直した項目"
        assert "読み込みました" in res.content.decode()
        assert EvaluationTemplate.unscoped.count() == 1

    def test_確認だけでは入れ替えない(self, client, admin_user, template):
        from django.core.files.uploadedfile import SimpleUploadedFile

        client.force_login(admin_user)
        body = json.dumps({
            "format": "kem-eval-template", "version": 1,
            "sections": [{"section": "共通", "num": 1, "name": "直した項目"}],
        }, ensure_ascii=False).encode()

        res = client.post(reverse("workers:eval_template_import"), {
            "payload": SimpleUploadedFile(
                "eval_template.json", body, content_type="application/json",
            ),
        }, follow=True)

        template.refresh_from_db()
        assert template.sections[0]["name"] == "報連相"
        assert "こうなります" in res.content.decode()

    def test_評価項目のファイルなら行き先を教える(self, client, admin_user, template):
        """テンプレートの画面に評価項目のファイルを入れたとき（2026-09-19）。"""
        from django.core.files.uploadedfile import SimpleUploadedFile

        client.force_login(admin_user)
        body = json.dumps({"format": "kem-eval-items", "items": []}).encode()

        res = client.post(reverse("workers:eval_template_import"), {
            "payload": SimpleUploadedFile(
                "eval_items.json", body, content_type="application/json",
            ),
        }, follow=True)

        assert "評価基準 から読み込んで" in res.content.decode()

    def test_admin以外は使えない(self, client, company_a, user_a, template):
        client.force_login(user_a)

        assert client.get(reverse("workers:eval_template_export")).status_code == 403


@pytest.mark.django_db
class TestTemplateAccess:
    """評価テンプレートを開ける人（ADR-0104）。"""

    @pytest.fixture
    def template(self, company_a):
        from apps.workers.models import EvaluationTemplate

        return EvaluationTemplate.unscoped.create(
            company=company_a, name="人材評価", sections=[], survey_items=[],
            scale=[], overall=[],
        )

    def _worker(self, company, user, *, code="E01", position=None, job_title=None):
        from apps.workers.models import JobTitle, Position, Worker

        return Worker.unscoped.create(
            company=company, name="担当者", employee_code=code, user=user,
            position=(
                Position.unscoped.create(company=company, name=position)
                if position else None
            ),
            job_title=(
                JobTitle.unscoped.create(company=company, name=job_title)
                if job_title else None
            ),
        )

    @pytest.mark.parametrize(("code", "position", "job_title"), [
        ("Y01", None, None),          # 社員番号 Y 始まりの管理者
        ("E01", None, "ITインフラ"),   # 職種が IT
        ("E02", "社長", None),         # 社長
        ("E03", "役員", None),         # 役員
    ])
    def test_開ける人(self, client, company_a, user_a, template, code, position, job_title):
        self._worker(company_a, user_a, code=code, position=position, job_title=job_title)
        client.force_login(user_a)

        assert client.get(reverse("workers:eval_template_edit")).status_code == 200

    def test_ふつうの作業員は開けない(self, client, company_a, user_a, template):
        self._worker(company_a, user_a, code="E09", position="正社員", job_title="電工")
        client.force_login(user_a)

        assert client.get(reverse("workers:eval_template_edit")).status_code == 403
