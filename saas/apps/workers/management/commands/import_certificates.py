"""資格証のPDFを、作業員の保有資格に添付する（ADR-0082）。

個人書類なのでファイルはリポジトリに置かない。サーバーにフォルダを置いて実行する。

    # 何が起きるか見るだけ（既定）
    docker compose exec web python manage.py import_certificates \
        --dir /app/import/資格書一覧 --dates /app/import/資格書一覧/有効期限.csv

    # 実際に添付する
    docker compose exec web python manage.py import_certificates \
        --dir /app/import/資格書一覧 --dates /app/import/資格書一覧/有効期限.csv --apply
"""

from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Company
from apps.workers.certificate_import import import_certificates, read_dates
from apps.workers.listed_qualifications import find_company
from apps.workers.models import Worker, WorkerQualification


class Command(BaseCommand):
    help = "資格証のPDFを作業員の保有資格に添付する（既定は確認のみ）"

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True, help="資格書一覧フォルダ")
        parser.add_argument("--dates", default="", help="有効期限のCSV")
        parser.add_argument("--company", default="", help="会社名（省略時はケンモチ電機）")
        parser.add_argument("--apply", action="store_true", help="実際に添付する")

    def handle(self, *args, **options):
        if options["company"]:
            company = Company._base_manager.filter(name=options["company"]).first()
        else:
            company = find_company(Company)
        if company is None:
            raise CommandError("登録先の会社が見つかりません。--company で指定してください。")

        dates = read_dates(options["dates"] or None)
        report = import_certificates(
            options["dir"], company, Worker, WorkerQualification,
            dates=dates, apply=options["apply"],
        )

        self.stdout.write(f"会社: {company.name}")
        self.stdout.write("")
        self.stdout.write("作業員 | 資格名 | ファイル | 有効期限")
        for person, name, file_name, expiry in report["attached"]:
            self.stdout.write(f"{person} | {name} | {file_name} | {expiry or '-'}")

        self._section("保有資格を新しく作る", report["created"])
        self._section("前の添付を差し替える", report["replaced"])
        self._section("同じ資格の2枚目以降（添付しない）", report["skipped_duplicate"])
        self._section("読み替え表に無いファイル", report["unknown_file"])
        self._section("作業員が見つからない", report["unknown_worker"])

        self.stdout.write("")
        summary = (
            f"添付 {len(report['attached'])} 件 / "
            f"新規 {len(report['created'])} 件 / "
            f"差し替え {len(report['replaced'])} 件"
        )
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"{summary}（登録しました）"))
        else:
            self.stdout.write(f"{summary}（確認のみ。--apply で登録します）")

    def _section(self, title, rows):
        if not rows:
            return
        self.stdout.write("")
        self.stdout.write(f"[{title}] {len(rows)} 件")
        for row in rows:
            text = " | ".join(map(str, row)) if isinstance(row, tuple) else str(row)
            self.stdout.write(f"  {text}")
