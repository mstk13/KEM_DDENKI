"""人材管理のビジネスロジック。

スキルマップ、勤怠集計、資格期限チェックを担う。
将来の DRF API 移行時にもそのまま使える。
"""

from datetime import date

from django.db.models import Count, Sum

from apps.workers.models import Worker, WorkerQualification


def get_skill_map(company):
    """全作業員のスキルマップを取得する。

    Returns:
        {
            "workers": [{"name": "田中", "skills": {"配線": 4, "電灯": 3}}, ...],
            "all_skills": ["配線", "電灯", "盤工事", ...],
        }
    """
    workers = Worker.unscoped.filter(company=company, is_active=True)

    all_skills = set()
    worker_data = []

    for w in workers:
        skills = {}
        for tag in (w.skill_tags or []):
            if isinstance(tag, dict):
                name = tag.get("name", "")
                level = tag.get("level", 1)
            else:
                name = str(tag)
                level = 1
            skills[name] = level
            all_skills.add(name)

        worker_data.append({
            "pk": w.pk,
            "name": w.name,
            "skills": skills,
        })

    return {
        "workers": worker_data,
        "all_skills": sorted(all_skills),
    }


def get_attendance_summary(company, year, month):
    """月別勤怠集計。日報の承認済みデータから自動集計する。

    Returns:
        [{
            "worker_name": "田中太郎",
            "worker_pk": 1,
            "work_days": 22,
            "total_regular": 176.0,
            "total_overtime": 15.5,
            "total_hours": 191.5,
        }, ...]
    """
    from apps.reports.models import DailyReport

    reports = DailyReport.unscoped.filter(
        company=company,
        report_date__year=year,
        report_date__month=month,
        status=DailyReport.Status.APPROVED,
    )

    summary = (
        reports.values("worker__name", "worker__pk")
        .annotate(
            work_days=Count("report_date", distinct=True),
            total_regular=Sum("regular_hours"),
            total_overtime=Sum("overtime_hours"),
            total_hours=Sum("work_hours"),
        )
        .order_by("worker__name")
    )

    return [
        {
            "worker_name": r["worker__name"],
            "worker_pk": r["worker__pk"],
            "work_days": r["work_days"],
            "total_regular": float(r["total_regular"] or 0),
            "total_overtime": float(r["total_overtime"] or 0),
            "total_hours": float(r["total_hours"] or 0),
        }
        for r in summary
    ]


def get_expiring_qualifications(company, days_ahead=90):
    """期限が近い資格の一覧を取得する。

    Returns:
        [{"worker_name", "qual_name", "expiry_date", "days_remaining"}, ...]
    """
    from datetime import timedelta

    today = date.today()
    threshold = today + timedelta(days=days_ahead)

    quals = WorkerQualification.unscoped.filter(
        company=company,
        expiry_date__isnull=False,
        expiry_date__lte=threshold,
    ).select_related("worker").order_by("expiry_date")

    return [
        {
            "worker_name": q.worker.name,
            "qual_name": q.name,
            "expiry_date": q.expiry_date,
            "days_remaining": (q.expiry_date - today).days,
            "pk": q.pk,
        }
        for q in quals
    ]


def setup_developer_worker(worker, created_by=None):
    """職種=ITインフラ, 役職=Developer の作業員にユーザーアカウント+権限を自動設定する。

    - Userアカウントを作成（username=社員番号, 初期パスワード=社員番号）
    - developerロールを付与
    - allowed_appsにdevkanriを追加

    Returns:
        User インスタンス（作成済みの場合は既存を返す）
    """
    from apps.accounts.models import User
    from apps.permissions.models import Role, UserRole

    if worker.user:
        return worker.user

    # ユーザーアカウント作成
    username = worker.employee_code or f"dev-{worker.pk}"
    user = User.objects.create_user(
        username=username,
        password=username,  # 初期パスワード=社員番号（初回ログイン時に変更を促す）
        company=worker.company,
    )
    user.first_name = worker.name
    user.save()

    # Workerに紐づけ
    worker.user = user
    # devkanriをallowed_appsに追加
    apps = worker.allowed_apps or []
    if "devkanri" not in apps:
        apps.append("devkanri")
    worker.allowed_apps = apps
    worker.save(update_fields=["user", "allowed_apps"])

    # developerロールを付与
    developer_role = Role.unscoped.filter(
        company=worker.company, code="developer",
    ).first()
    if developer_role:
        UserRole.unscoped.get_or_create(
            company=worker.company,
            user=user,
            role=developer_role,
            defaults={"granted_by": created_by},
        )

    return user


def is_developer_worker(worker):
    """職種=ITインフラ かつ 役職=Developer かを判定する。"""
    job = worker.job_title.name if worker.job_title else ""
    pos = worker.position.name if worker.position else ""
    return job == "ITインフラ" and pos == "Developer"
