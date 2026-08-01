from django.urls import path

from apps.costs import views

app_name = "costs"

urlpatterns = [
    path("", views.cost_list, name="list"),
]
