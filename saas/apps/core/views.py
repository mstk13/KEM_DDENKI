from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@login_required
def dashboard(request):
    today = timezone.now().date()
    context = {
        "active_sites": Site.objects.filter(status=Site.Status.IN_PROGRESS).count(),
        "today_reports": DailyReport.objects.filter(report_date=today).count(),
        "pending_reports": DailyReport.objects.filter(
            status=DailyReport.Status.SUBMITTED
        ).count(),
        "active_workers": Worker.objects.filter(is_active=True).count(),
        "recent_sites": Site.objects.filter(
            status=Site.Status.IN_PROGRESS
        ).select_related("customer")[:5],
        "recent_reports": DailyReport.objects.select_related(
            "worker", "site"
        ).order_by("-report_date", "-created_at")[:10],
    }
    return render(request, "dashboard.html", context)
