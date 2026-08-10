from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("", views.employee_login, name="login"),
    path("check-code/", views.check_employee_code, name="check_employee_code"),
    path("setup-pin/", views.setup_pin, name="setup_pin"),
    path("change-pin/", views.change_pin, name="change_pin"),
]
