import datetime

from django.urls import path, register_converter

from apps.safety import views


class IsoDateConverter:
    """URL の日付（2026-09-15）。日付として無いもの（2026-13-40）は 404 にする。"""

    regex = r"\d{4}-\d{2}-\d{2}"

    def to_python(self, value):
        return datetime.date.fromisoformat(value)  # ValueError なら URL に一致しない（404）

    def to_url(self, value):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)


register_converter(IsoDateConverter, "isodate")

app_name = "safety"

urlpatterns = [
    path("sites/<int:site_pk>/", views.site_safety, name="site"),
    # KY用紙（安全作業指示書）
    path("sites/<int:site_pk>/ky/<isodate:day>/", views.ky_sheet, name="ky_sheet"),
    path("sites/<int:site_pk>/ky/<isodate:day>/sign/", views.ky_sign, name="ky_sign"),
    path("ky/<int:pk>/pdf/", views.ky_pdf, name="ky_pdf"),
    path("ky/<int:pk>/signoff/<str:kind>/", views.ky_signoff, name="ky_signoff"),
    path(
        "ky/participants/<int:pk>/delete/",
        views.ky_participant_delete,
        name="ky_participant_delete",
    ),
    # 安全作業確認書（新規入場者用）
    path("sites/<int:site_pk>/entry/new/", views.entry_create, name="entry_create"),
    path("entry/<int:pk>/", views.entry_detail, name="entry_detail"),
    path("entry/<int:pk>/edit/", views.entry_edit, name="entry_edit"),
    path("entry/<int:pk>/pdf/", views.entry_pdf, name="entry_pdf"),
]
