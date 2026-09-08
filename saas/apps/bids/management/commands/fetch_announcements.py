"""取り込み済みの入札案件について、公告PDFから工事概要・参加要件を埋める。

スクレイプ時にも取りに行くが、公告の取得だけ失敗した案件や、
この機能より前に取り込んだ案件を後から埋めるために使う。

    python manage.py fetch_announcements
    python manage.py fetch_announcements --company ケンモチ電機 --limit 20
"""
from django.core.management.base import BaseCommand

from apps.bids.models import BidProject
from apps.bids.services import fill_announcements


class Command(BaseCommand):
    help = "入札案件の情報源URL（公告PDF）から工事概要・参加要件を取り込む"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", help="会社名（部分一致）。省略時は全テナント",
        )
        parser.add_argument(
            "--limit", type=int, help="取りに行く件数の上限",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="工事概要・参加要件・手続きスケジュールが入っている案件も取り直す",
        )

    def handle(self, *args, **options):
        # unscoped: 会社を跨いで一括処理するコマンドのため
        qs = BidProject.unscoped.exclude(source_url="")
        if options["company"]:
            qs = qs.filter(company__name__icontains=options["company"])
        if not options["force"]:
            qs = qs.filter(work_outline="") | qs.filter(requirements="")
        qs = qs.distinct().order_by("-announced_on", "pk")

        projects = list(qs)
        if options["force"]:
            for project in projects:
                project.work_outline = ""
                project.requirements = ""
                # 別表の読み取りを直したときに古い日程が残らないようにする。
                # fill_announcement は空のときしか書かないため、ここで消しておく。
                project.bid_schedule = []

        self.stdout.write(f"対象 {len(projects)} 件")
        filled = fill_announcements(projects, limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(f"{filled} 件に取り込みました"))
