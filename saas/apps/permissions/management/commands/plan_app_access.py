"""今の実効権限から、機能別の利用者リスト（AppAccess）の案を出す（ADR-0030・ADR-0045）。

    python manage.py plan_app_access            # 機能ごとの案と差分を出す（書き込まない）
    python manage.py plan_app_access --matrix   # 作業員 × 機能 の表を CSV で出す
    python manage.py plan_app_access --apply    # AppAccess を案どおりにする

判定を利用者リストに切り替える前に、「誰に何が開くか」をプロダクトオーナーが確かめるために使う（D2）。
切り替えた後に --apply を流すと、画面で直した利用者リストを今の判定で上書きしてしまうので流さない。
"""
import csv

from django.core.management.base import BaseCommand, CommandError

from apps.permissions.app_registry import APPS
from apps.permissions.legacy_access import legacy_access_plan, sync_app_access
from apps.tenants.models import Company


def _label(worker) -> str:
    return f"{worker.employee_code or '-'} {worker.name}"


def _mark(access: dict[str, bool], app_key: str) -> str:
    if app_key not in access:
        return ""
    return "承認" if access[app_key] else "○"


class Command(BaseCommand):
    help = "今の実効権限から機能別の利用者リスト（AppAccess）の案を出す。--apply で反映する"

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, help="会社ID。省略するとすべての会社")
        parser.add_argument(
            "--matrix",
            action="store_true",
            help="作業員 × 機能 の表を CSV で出す（書き込まない）",
        )
        parser.add_argument("--apply", action="store_true", help="AppAccess を案どおりにする")

    def handle(self, *args, **options):
        if options["apply"] and options["matrix"]:
            raise CommandError("--apply と --matrix は同時に指定できません")

        companies = Company.objects.order_by("pk")
        if options["company"] is not None:
            companies = companies.filter(pk=options["company"])
            if not companies.exists():
                raise CommandError(f"会社ID {options['company']} が見つかりません")

        if options["matrix"]:
            self._write_matrix(companies)
            return

        for company in companies:
            plan = legacy_access_plan(company)
            self._write_summary(company, plan)
            result = sync_app_access(company, plan, apply=options["apply"])
            state = "反映しました" if options["apply"] else "--apply で反映します"
            self.stdout.write(
                f"AppAccess: 追加 {result.created}・承認の変更 {result.updated}・"
                f"削除 {result.deleted}（{state}）",
            )
            self.stdout.write("")

    def _write_summary(self, company, plan):
        total = len(plan)
        self.stdout.write(f"== {company.name}（在籍 {total} 人）")
        for app in APPS:
            allowed = [worker for worker, access in plan if app.key in access]
            denied = [worker for worker, access in plan if app.key not in access]
            line = f"{app.label}: {len(allowed)}/{total} 人"
            if allowed and denied:
                # 少ないほうの名前を出す（全員使える機能で全員の名前を並べても読めない）
                if len(denied) <= len(allowed):
                    line += f"（使えない: {'、'.join(_label(w) for w in denied)}）"
                else:
                    line += f"（使える: {'、'.join(_label(w) for w in allowed)}）"
            if app.approvable:
                approvers = [worker for worker, access in plan if access.get(app.key)]
                line += f" 承認できる: {'、'.join(_label(w) for w in approvers) or 'なし'}"
            self.stdout.write(line)

    def _write_matrix(self, companies):
        writer = csv.writer(self.stdout, lineterminator="\n")
        writer.writerow(
            ["会社", "社員番号", "氏名", "役職", "ログイン", *[app.label for app in APPS]],
        )
        for company in companies:
            for worker, access in legacy_access_plan(company):
                writer.writerow([
                    company.name,
                    worker.employee_code,
                    worker.name,
                    worker.position.name if worker.position_id else "",
                    "あり" if worker.user_id else "なし",
                    *[_mark(access, app.key) for app in APPS],
                ])
