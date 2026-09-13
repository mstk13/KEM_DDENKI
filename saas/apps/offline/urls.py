from django.urls import path

from apps.offline import views

app_name = "offline"

urlpatterns = [
    path("", views.outbox, name="outbox"),
]
