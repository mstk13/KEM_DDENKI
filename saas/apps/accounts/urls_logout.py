from django.urls import path

from apps.accounts.views import employee_logout

urlpatterns = [
    path("", employee_logout, name="logout"),
]
