from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from apps.costs.models import CostTransaction
from apps.sites.models import Site


@login_required
def cost_list(request):
    sites = Site.objects.filter(
        status__in=[Site.Status.IN_PROGRESS, Site.Status.COMPLETED],
    )

    site_costs = []
    for site in sites:
        total_cost = (
            CostTransaction.objects.filter(site=site).aggregate(t=Sum("amount"))["t"]
            or 0
        )
        gross_profit = site.contract_amount - total_cost
        margin_rate = (
            (gross_profit / site.contract_amount * 100)
            if site.contract_amount
            else None
        )
        site_costs.append({
            "site": site,
            "total_cost": total_cost,
            "gross_profit": gross_profit,
            "margin_rate": margin_rate,
        })

    transactions = CostTransaction.objects.select_related(
        "site", "work_type", "cost_category",
    ).order_by("-transaction_date")[:20]

    return render(request, "costs/list.html", {
        "site_costs": site_costs,
        "transactions": transactions,
    })
