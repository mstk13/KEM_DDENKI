from django.urls import path

from apps.notifications import views

urlpatterns = [
    path("", views.notification_list, name="notification_list"),
    path("<int:pk>/read/", views.notification_read, name="notification_read"),
    path("read-all/", views.notification_read_all, name="notification_read_all"),
    path("badge/", views.notification_badge, name="notification_badge"),
]
