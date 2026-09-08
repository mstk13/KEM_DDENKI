"""案件詳細の「前の案件／次の案件」と、確認付きの削除。"""

import datetime

import pytest

from apps.bids.models import BidCost, BidProject


def _make(company, user, title, announced_on):
    return BidProject.unscoped.create(
        company=company, created_by=user, title=title, client="国土交通省",
        category="電気", announced_on=announced_on,
        deadline=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
    )


@pytest.fixture
def three(company_a, user_a):
    """一覧の既定順（公告日の新しい順）で A → B → C になる3件。"""
    c = _make(company_a, user_a, "案件C", datetime.date(2026, 9, 1))
    b = _make(company_a, user_a, "案件B", datetime.date(2026, 9, 2))
    a = _make(company_a, user_a, "案件A", datetime.date(2026, 9, 3))
    return a, b, c


@pytest.mark.django_db
class TestPrevNext:
    def test_follows_list_order(self, client, user_a, three):
        a, b, c = three
        client.force_login(user_a)

        html = client.get(f"/bids/{b.pk}/").content.decode()
        assert f'href="/bids/{a.pk}/"' in html  # 前の案件
        assert f'href="/bids/{c.pk}/"' in html  # 次の案件

    def test_ends_are_disabled(self, client, user_a, three):
        a, b, c = three
        client.force_login(user_a)

        first = client.get(f"/bids/{a.pk}/").content.decode()
        assert f'href="/bids/{b.pk}/"' in first
        assert "pointer-events:none;\">&larr; 前の案件" in first

        last = client.get(f"/bids/{c.pk}/").content.decode()
        assert f'href="/bids/{b.pk}/"' in last
        assert "pointer-events:none;\">次の案件" in last

    def test_uses_saved_filter(self, client, user_a, three):
        """一覧で絞り込んだ状態なら、その並びの中で前後を辿る。"""
        a, b, c = three
        client.force_login(user_a)
        client.get("/bids/?q=案件A")  # 絞り込みをセッションに保存
        a.title = "案件A"
        c.title = "案件A2"
        c.save()

        html = client.get(f"/bids/{a.pk}/").content.decode()
        # B は絞り込みに掛からないので飛ばして C に行く
        assert f'href="/bids/{c.pk}/"' in html
        assert f'href="/bids/{b.pk}/"' not in html

    def test_detail_does_not_change_saved_filter(self, client, user_a, three):
        a, b, c = three
        client.force_login(user_a)
        client.get("/bids/?q=案件B")
        client.get(f"/bids/{a.pk}/")
        assert client.session["bid_filter_q"] == "案件B"


@pytest.mark.django_db
class TestDelete:
    def test_post_deletes_with_cost(self, client, company_a, user_a, three):
        a, _b, _c = three
        BidCost.unscoped.create(
            company=company_a, created_by=user_a, project=a,
            estimate_amount=1000, actual_cost=900,
        )
        client.force_login(user_a)
        response = client.post(f"/bids/{a.pk}/delete/")
        assert response.status_code == 302
        assert response.url == "/bids/"
        assert not BidProject.unscoped.filter(pk=a.pk).exists()
        assert not BidCost.unscoped.filter(project_id=a.pk).exists()

    def test_get_does_not_delete(self, client, user_a, three):
        a, _b, _c = three
        client.force_login(user_a)
        response = client.get(f"/bids/{a.pk}/delete/")
        assert response.status_code == 302
        assert BidProject.unscoped.filter(pk=a.pk).exists()

    def test_button_has_confirm(self, client, user_a, three):
        a, _b, _c = three
        client.force_login(user_a)
        html = client.get(f"/bids/{a.pk}/").content.decode()
        assert f'action="/bids/{a.pk}/delete/"' in html
        assert "confirm(" in html

    def test_other_tenant_is_404(self, client, user_b, three):
        a, _b, _c = three
        client.force_login(user_b)
        assert client.post(f"/bids/{a.pk}/delete/").status_code == 404
        assert BidProject.unscoped.filter(pk=a.pk).exists()
