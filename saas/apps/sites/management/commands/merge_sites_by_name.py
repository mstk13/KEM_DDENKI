"""現場名を指定して、二重登録をまとめる（ADR-0090）。

画面の「手で選んでまとめる」と**同じ道筋**を通る。違うのは、選ぶのが
プルダウンではなく現場名だという点だけ。記録の付け替えも、取り消しのための
候補の行も、画面と同じ `merge_sites` / `candidate_for` が行う。

なぜコマンドも要るのか:

* 表記ゆれが5件10件とあるとき、画面で2つずつ選ぶのは数が多い
* 「何が起きるか」を**書き込む前に**確かめたい。画面は押すと即座に動く
* サーバ上で1行流せば済むので、画面を開けない人にも頼める

**既定では書き込まない。** `--apply` を付けたときだけ実際に統合する。
付けずに流すと、どの現場がいくつの記録を持っていて、何がどこへ動くかを出す。

使い方:

    # まず確かめる（書き込まない）
    docker compose exec web python manage.py merge_sites_by_name \
        --keep 高橋住宅 --merge 高橋アパート

    # 実際にまとめる
    docker compose exec web python manage.py merge_sites_by_name \
        --keep 高橋住宅 --merge 高橋アパート --apply

    # 3つ以上をまとめ、最後に名前を揃える
    docker compose exec web python manage.py merge_sites_by_name \
        --keep 厚木あゆ祭り --merge あゆ祭り --merge 厚木鮎まつり \
        --rename 厚木鮎祭り --apply

現場名が複数の会社にあるときは `--company 会社名` で絞る。
同じ会社に同じ名前の現場が2つあるときは、どちらか分からないので止める。
"""

from django.core.management.base import BaseCommand, CommandError

from apps.sites.merge import candidate_for, merge_sites
from apps.sites.merge_candidates import _row_count
from apps.sites.models import Site
from apps.tenants.models import Company


class Command(BaseCommand):
    help = "現場名を指定して二重登録をまとめる（--apply を付けるまで書き込まない）"

    def add_arguments(self, parser):
        parser.add_argument("--keep", required=True, help="残す現場の名前")
        parser.add_argument(
            "--merge", action="append", default=[], required=True,
            help="まとめる現場の名前。繰り返し指定できる",
        )
        parser.add_argument("--rename", default="", help="まとめたあとの現場名")
        parser.add_argument("--company", default="", help="会社名（同名の現場が他社にもあるとき）")
        parser.add_argument(
            "--apply", action="store_true", help="実際に書き込む（付けないと確認だけ）",
        )

    def handle(self, *args, **options):
        company = self._company(options["company"])
        primary = self._site(company, options["keep"])
        duplicates = [self._site(company, name) for name in options["merge"]]

        for duplicate in duplicates:
            if duplicate.pk == primary.pk:
                raise CommandError(f"「{primary.name}」を自分自身にはまとめられません。")

        self.stdout.write(f"残す現場: {primary.name}（記録 {_row_count(primary)} 件）")
        for duplicate in duplicates:
            self.stdout.write(
                f"  ← {duplicate.name}（記録 {_row_count(duplicate)} 件）",
            )
        if options["rename"]:
            self.stdout.write(f"まとめたあとの名前: {options['rename']}")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "確認だけで、何も書き込んでいません。"
                    "実行するには --apply を付けてください。",
                ),
            )
            return

        moved_total = 0
        for duplicate in duplicates:
            # 画面と同じ道筋を通す。候補の行が無いと取り消せない（ADR-0090）
            candidate = candidate_for(company, primary, duplicate)
            result = merge_sites(primary, duplicate, candidate=candidate)
            moved = sum(result["moved"].values())
            moved_total += moved
            self.stdout.write(
                f"「{duplicate.name}」→「{primary.name}」に {moved} 件を付け替えました。",
            )
            for label, count in result["conflicts"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {label} の {count} 件は、同じ内容が既にあるため動かしていません。"
                        f"「{duplicate.name}」に残っています。",
                    ),
                )

        if options["rename"] and options["rename"] != primary.name:
            old_name = primary.name
            primary.name = options["rename"][:200]
            primary.save(update_fields=["name", "updated_at"])
            self.stdout.write(f"現場名を「{old_name}」から「{primary.name}」に変えました。")

        self.stdout.write(
            self.style.SUCCESS(
                f"完了（合計 {moved_total} 件を付け替え）。"
                "取り消しは 現場 > 名寄せ の「統合の履歴」から。",
            ),
        )

    def _company(self, name):
        qs = Company.objects.filter(name=name) if name else Company.objects.all()
        found = list(qs[:2])
        if not found:
            raise CommandError(f"会社が見つかりません: {name!r}")
        if len(found) > 1:
            raise CommandError("会社が複数あります。--company で会社名を指定してください。")
        return found[0]

    def _site(self, company, name):
        """現場名から現場を引く。統合済みの現場は選べない。"""
        # unscoped: コマンドはテナントコンテキストの外で動くため company で明示的に絞る
        found = list(
            Site.unscoped.filter(company=company, name=name, merged_into__isnull=True)[:2],
        )
        if not found:
            merged = Site.unscoped.filter(company=company, name=name).first()
            if merged is not None:
                raise CommandError(
                    f"「{name}」は既に「{merged.merged_into.name}」にまとめてあります。",
                )
            raise CommandError(f"現場が見つかりません: {name!r}（{company.name}）")
        if len(found) > 1:
            raise CommandError(
                f"「{name}」という現場が {company.name} に2つ以上あります。"
                "画面の「手で選んでまとめる」から選んでください。",
            )
        return found[0]
