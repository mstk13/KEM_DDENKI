"""資格保有一覧.xls の資格を作業員ごとに登録する（ADR-0068）。

データ移送（workers/0018・0019）でも登録・入れ替えをしている。作業員が見つからなかった人を
確かめたり、作業員の氏名を直したあとに登録し直したりするときに使う。
一覧に載っている作業員の資格は、この一覧のものだけにする。
一覧に無い資格は、原本の写真が付いていても消す。

使い方:
    python manage.py register_listed_qualifications            # 確認だけ（何も変えない）
    python manage.py register_listed_qualifications --apply    # 登録する
"""

from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Company
from apps.workers.listed_qualifications import (
    HOLDERS,
    SOURCE,
    find_company,
    register_listed_qualifications,
)
from apps.workers.models import Worker, WorkerQualification


class Command(BaseCommand):
    help = "資格保有一覧.xls の資格を作業員ごとに登録する"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="登録する（省略時は確認だけ）")
        parser.add_argument(
            "--company", type=int, default=None,
            help="対象の会社ID（省略時は「ケンモチ電機」、無ければ唯一の会社）",
        )

    def handle(self, *args, **options):
        if options["company"]:
            company = Company.objects.filter(pk=options["company"]).first()
        else:
            company = find_company(Company)
        if company is None:
            raise CommandError("登録先の会社が決まりません。--company で指定してください。")

        apply = options["apply"]
        report = register_listed_qualifications(
            company, Worker, WorkerQualification, apply=apply,
        )
        write = self.stdout.write
        write(f"会社: {company.name} / 原本: {SOURCE}（{len(HOLDERS)} 人）")
        write("登録しました" if apply else "確認だけです（登録するときは --apply）")

        counts = {}
        for worker_name, _name in report["created"]:
            counts[worker_name] = counts.get(worker_name, 0) + 1
        write(f"■ {'登録' if apply else '登録予定'} {len(report['created'])} 件")
        for worker_name, count in counts.items():
            write(f"- {worker_name}: {count} 件")
        write(f"■ 既に登録済みで飛ばした資格 {len(report['existing'])} 件")
        if report["removed"]:
            write(
                f"■ 一覧に無い資格 {len(report['removed'])} 件"
                f"（{'消しました' if apply else '消す予定'}）"
            )
            for worker_name, name in report["removed"]:
                write(f"- {worker_name}: {name}")
        if report["removed_with_image"]:
            write(
                f"■ 消したうち原本の写真が付いていた資格 {len(report['removed_with_image'])} 件"
                "（写真も見られなくなります）"
            )
            for worker_name, name in report["removed_with_image"]:
                write(f"- {worker_name}: {name}")
        if report["missing"]:
            write(
                f"■ 作業員が見つからない氏名 {len(report['missing'])} 人"
                "（作業員の氏名を確かめてください）"
            )
            for name in report["missing"]:
                write(f"- {name}")
            registered = list(
                Worker.objects.filter(company=company, is_active=True)
                .order_by("employee_code", "pk")
                .values_list("employee_code", "name")
            )
            write(f"■ 登録されている在籍中の作業員 {len(registered)} 人（氏名の書き方の確認用）")
            for code, name in registered:
                write(f"- {code or '（社員番号なし）'} {name}")
        if report["ambiguous"]:
            write(
                f"■ 同じ氏名の作業員が複数いる {len(report['ambiguous'])} 人（登録していません）"
            )
            for name in report["ambiguous"]:
                write(f"- {name}")
