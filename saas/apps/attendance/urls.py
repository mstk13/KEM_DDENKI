from django.urls import path
from django.views.generic import RedirectView

from apps.attendance import views

app_name = "attendance"

urlpatterns = [
    # 勤怠日報は reports（日報）と実績が重複するため廃止した。ADR-0024 を参照。
    # /attendance/ は出社予定を入口にする。
    path("", RedirectView.as_view(pattern_name="attendance:plan_board")),
    # 出社予定
    path("plans/", views.plan_board, name="plan_board"),
    path("plans/day/", views.plan_day, name="plan_day"),
    path("plans/set/", views.plan_set, name="plan_set"),
    # 1人1日ぶんの予定（1日を時間で分けた複数件）をまとめて保存する。ADR-0038
    path("plans/entries/", views.plan_entries, name="plan_entries"),
    path("plans/fill/", views.plan_fill, name="plan_fill"),
    path("plans/clear-day/", views.plan_clear_day, name="plan_clear_day"),
    path("settings/", views.settings_view, name="settings"),
]
