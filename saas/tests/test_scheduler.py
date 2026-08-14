"""定期実行スケジューラのテスト。

cron コンテナは crontab / crond がイメージに無く exit 127 で
再起動を繰り返しており、scrape_bids と send_document_alerts が
一度も実行されていなかった。その代替である run_scheduler の
スケジュール判定を検証する。
"""

from datetime import datetime
from unittest.mock import patch

from django.core.management import call_command

from apps.core.management.commands.run_scheduler import JOBS, Job


def at(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, month, day, hour, minute)


class TestJobSchedule:
    def test_daily_job_runs_at_its_time(self):
        job = Job(name="毎日", command="noop", hour=8)
        assert job.is_due(at(8, 14, 8, 0)) is True

    def test_daily_job_does_not_run_at_other_times(self):
        job = Job(name="毎日", command="noop", hour=8)
        assert job.is_due(at(8, 14, 7, 0)) is False
        assert job.is_due(at(8, 14, 8, 1)) is False
        assert job.is_due(at(8, 14, 9, 0)) is False

    def test_minute_is_respected(self):
        job = Job(name="30分", command="noop", hour=8, minute=30)
        assert job.is_due(at(8, 14, 8, 30)) is True
        assert job.is_due(at(8, 14, 8, 0)) is False

    def test_every_two_days_alternates(self):
        job = Job(name="2日毎", command="noop", hour=7, every_n_days=2)
        # 通年日で判定する。連続する2日で必ず片方だけ True になる。
        first = job.is_due(at(8, 14, 7, 0))
        second = job.is_due(at(8, 15, 7, 0))
        assert first != second

    def test_every_two_days_keeps_interval_across_months(self):
        """月をまたいでも間隔が崩れないこと。

        日付(day)で判定すると月末31日→翌月1日で間隔が壊れる。
        通年日で判定しているのでそれが起きない。
        """
        job = Job(name="2日毎", command="noop", hour=7, every_n_days=2)
        # 8/31 と 9/1 は連続する日。片方だけ True になるはず。
        assert job.is_due(at(8, 31, 7, 0)) != job.is_due(at(9, 1, 7, 0))


class TestRegisteredJobs:
    """旧 crontab と同じ内容が登録されていること。"""

    def test_expected_commands_are_registered(self):
        commands = {job.command for job in JOBS}
        assert commands == {"scrape_bids", "send_document_alerts"}

    def test_scrape_bids_runs_every_two_days_at_seven(self):
        job = next(j for j in JOBS if j.command == "scrape_bids")
        assert (job.hour, job.minute, job.every_n_days) == (7, 0, 2)
        assert job.options == {"force": True}

    def test_document_alerts_runs_daily_at_eight(self):
        job = next(j for j in JOBS if j.command == "send_document_alerts")
        assert (job.hour, job.minute, job.every_n_days) == (8, 0, 1)


class TestSchedulerLoop:
    def test_once_returns_without_running_anything_off_schedule(self):
        """予定時刻でなければ何も実行せずに終了すること。"""
        with patch(
            "apps.core.management.commands.run_scheduler.call_command"
        ) as called:
            call_command("run_scheduler", "--once")
        assert called.call_count == 0

    def test_failing_job_does_not_stop_the_scheduler(self):
        """1つのジョブが落ちてもスケジューラは死なないこと。"""
        job = Job(name="失敗する", command="broken", hour=0, minute=0)
        with (
            patch(
                "apps.core.management.commands.run_scheduler.JOBS", [job]
            ),
            patch(
                "apps.core.management.commands.run_scheduler.call_command",
                side_effect=RuntimeError("boom"),
            ) as called,
            patch(
                "apps.core.management.commands.run_scheduler.timezone.localtime",
                return_value=at(8, 14, 0, 0),
            ),
        ):
            # 例外が外に漏れないこと
            call_command("run_scheduler", "--once")
        assert called.call_count == 1

    def test_due_job_is_executed_with_its_options(self):
        job = Job(
            name="実行される", command="scrape_bids", hour=7,
            options={"force": True},
        )
        with (
            patch("apps.core.management.commands.run_scheduler.JOBS", [job]),
            patch(
                "apps.core.management.commands.run_scheduler.call_command"
            ) as called,
            patch(
                "apps.core.management.commands.run_scheduler.timezone.localtime",
                return_value=at(8, 14, 7, 0),
            ),
        ):
            call_command("run_scheduler", "--once")
        called.assert_called_once_with("scrape_bids", force=True)
