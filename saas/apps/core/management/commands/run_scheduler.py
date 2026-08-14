"""定期実行スケジューラ。cron コンテナの代わりに常駐する。

なぜ cron を使わないのか:

1. イメージに cron が入っていない。python:3.12-slim には crontab も
   crond も無く、cron コンテナは exit 127 で再起動を繰り返していた。
   その間 scrape_bids と send_document_alerts は一度も走っていない。
2. Debian のデーモン名は crond ではなく cron。compose の
   `exec crond -f -l 2` は cron を入れても動かない。
3. 仮に両方直しても、cron のジョブはコンテナの環境変数を引き継がない。
   DB_HOST も ANTHROPIC_API_KEY も見えず、Django コマンドは
   DB に接続できずに失敗する。crontab へ環境変数を書き出す回避策はあるが、
   SECRET_KEY のような引用符を含む値で壊れやすい。

ジョブが2つしかないので、Django の管理コマンドとして常駐させるほうが
確実で、環境変数もそのまま引き継がれる。

    python manage.py run_scheduler
    python manage.py run_scheduler --once   # 起動確認用（1周だけ回して終了）
"""

import logging
import time
from dataclasses import dataclass, field

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """1つの定期ジョブ。"""

    name: str
    command: str
    hour: int
    minute: int = 0
    every_n_days: int = 1
    args: list = field(default_factory=list)
    options: dict = field(default_factory=dict)

    def is_due(self, now) -> bool:
        if now.hour != self.hour or now.minute != self.minute:
            return False
        if self.every_n_days <= 1:
            return True
        # 通年で数えた日で判定する。月をまたいでも間隔が崩れない。
        return now.timetuple().tm_yday % self.every_n_days == 0


# 旧 crontab と同じ内容。変更したらここだけ直せばよい。
JOBS = [
    Job(
        name="入札案件の自動取得",
        command="scrape_bids",
        hour=7,
        every_n_days=2,
        options={"force": True},
    ),
    Job(
        name="書類アラート（資格期限・健診期限等）",
        command="send_document_alerts",
        hour=8,
    ),
]


class Command(BaseCommand):
    help = "定期ジョブを常駐実行する（cron コンテナの代替）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true",
            help="1周だけ判定して終了する（起動確認用）",
        )
        parser.add_argument(
            "--interval", type=int, default=30,
            help="判定間隔の秒数（既定 30）",
        )

    def handle(self, *args, **options):
        self.stdout.write("=== スケジューラ起動 ===")
        for job in JOBS:
            every = (
                "毎日" if job.every_n_days <= 1 else f"{job.every_n_days}日ごと"
            )
            self.stdout.write(
                f"  {every} {job.hour:02d}:{job.minute:02d}  "
                f"{job.command}  ({job.name})"
            )

        interval = options["interval"]
        ran_at: dict[str, str] = {}

        while True:
            now = timezone.localtime()
            stamp = now.strftime("%Y-%m-%d %H:%M")

            for job in JOBS:
                # 同じ分に二重起動しない。判定間隔が1分未満のため必要。
                if ran_at.get(job.name) == stamp:
                    continue
                if not job.is_due(now):
                    continue

                ran_at[job.name] = stamp
                self.stdout.write(f"[{stamp}] 実行: {job.command} ({job.name})")
                started = time.monotonic()
                try:
                    call_command(job.command, *job.args, **job.options)
                except Exception:
                    # 1つのジョブの失敗でスケジューラ自体を止めない。
                    logger.exception("定期ジョブが失敗しました: %s", job.command)
                    self.stderr.write(
                        self.style.ERROR(f"[{stamp}] 失敗: {job.command}")
                    )
                else:
                    elapsed = time.monotonic() - started
                    self.stdout.write(
                        f"[{stamp}] 完了: {job.command} ({elapsed:.1f}秒)"
                    )

            if options["once"]:
                self.stdout.write("--once のため終了します。")
                return

            time.sleep(interval)
