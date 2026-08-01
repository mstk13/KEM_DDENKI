from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.masters.models import CostCategory, Customer, Supplier, WorkType


@login_required
def worktype_list(request):
    return render(request, "masters/worktypes.html", {
        "worktypes": WorkType.objects.all(),
        "cost_categories": CostCategory.objects.all(),
        "customers": Customer.objects.all(),
        "suppliers": Supplier.objects.all(),
    })
