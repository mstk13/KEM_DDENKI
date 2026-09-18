"""運転免許証の取得日・有効期限を入れる（ADR-0101）。

    docker compose exec web python manage.py fill_license_dates          # 確認だけ
    docker compose exec web python manage.py fill_license_dates --apply  # 登録する

券面の日付は apps/workers/license_dates.py に置いてある。
そこに無い人は「日付がまだ」として出るので、券面を見て足す。
"""

from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Company
from apps.workers.license_dates import fill_license_dates
from apps.workers.listed_qualifications import find_company
from apps.workers.models import WorkerQualification


class Command(BaseCommand):
    help = "運転免許証の取得日・有効期限を入れる（既定は確認のみ）"

    def add_arguments(self, parser):
        parser.add_argument("--company", default="", help="会社名（省略時はケンモチ電機）")
        parser.add_argument("--apply", action="store_true", help="実際に登録する")

    def handle(self, *args, **options):
        if options["company"]:
            company = Company._base_manager.filter(name=options["company"]).first()
        else:
            company = find_company(Company)
        if company is None:
            raise CommandError("会社が見つかりません。--company で指定してください。")

        report = fill_license_dates(
            company, WorkerQualification, apply=options["apply"],
        )

        for name, qualification, acquired, expiry in report["filled"]:
            self.stdout.write(f"{name} | {qualification} | 取得 {acquired} | 期限 {expiry}")
        for title, rows in (
            ("既に日付が入っている", report["already"]),
            ("券面の日付が手元に無い（日付がまだ）", report["unknown"]),
            ("資格証が付いていない", report["no_file"]),
        ):
            if not rows:
                continue
            self.stdout.write("")
            self.stdout.write(f"[{title}] {len(rows)} 件")
            for name, qualification in rows:
                self.stdout.write(f"  {name} | {qualification}")

        summary = f"入れた日付 {len(report['filled'])} 件"
        self.stdout.write("")
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"{summary}（登録しました）"))
        else:
            self.stdout.write(f"{summary}（確認のみ。--apply で登録します）")
