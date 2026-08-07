from django.conf import settings
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render

from apps.accounts.models import User
from apps.core.tenant_context import set_current_company
from apps.workers.models import Worker


def _find_worker_by_code(code):
    """社員番号からWorkerを検索（テナント横断）。"""
    return Worker.unscoped.select_related(
        "company", "job_title", "position",
    ).filter(employee_code=code, is_active=True).first()


def _is_president_worker(worker):
    """社長ポジションかどうか。"""
    return worker.position and worker.position.name == "社長"


def _get_or_create_user(worker):
    """WorkerにリンクされたDjango Userを取得/作成。"""
    if worker.user:
        return worker.user

    # 社員番号をユーザー名として作成
    username = f"emp_{worker.employee_code}"
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "company": worker.company,
            "employee_no": worker.employee_code,
            "first_name": worker.name,
        },
    )
    if created:
        # パスワードは使わない（社員番号ログインなので）
        user.set_unusable_password()
        user.save()
        worker.user = user
        worker.save(update_fields=["user"])

    # 社長はsuperuser権限
    if _is_president_worker(worker) and not user.is_superuser:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])

    return user


def check_employee_code(request):
    """社員番号の存在チェックAPI。社長の場合はPIN入力が必要なことを返す。"""
    code = request.GET.get("code", "").strip()
    if not code:
        return JsonResponse({"found": False})

    worker = _find_worker_by_code(code)
    if not worker:
        return JsonResponse({"found": False})

    return JsonResponse({
        "found": True,
        "name": worker.name,
        "needs_pin": _is_president_worker(worker),
    })


def employee_login(request):
    """社員番号ベースのログイン。"""
    error = ""

    if request.method == "POST":
        code = request.POST.get("employee_code", "").strip()
        pin = request.POST.get("pin", "").strip()

        worker = _find_worker_by_code(code)

        if not worker:
            error = "この社員番号は登録されていません"
        elif _is_president_worker(worker):
            if not pin:
                error = "管理者パスワードを入力してください"
            elif pin != settings.PRESIDENT_PIN:
                error = "管理者パスワードが正しくありません"
            else:
                user = _get_or_create_user(worker)
                set_current_company(worker.company)
                login(request, user)
                return redirect("dashboard")
        else:
            # 一般社員：社員番号だけでログイン
            user = _get_or_create_user(worker)
            set_current_company(worker.company)
            login(request, user)
            return redirect("dashboard")

    return render(request, "registration/login.html", {"error": error})


def employee_logout(request):
    """ログアウト。セッションを完全にクリアしてログイン画面へ。"""
    logout(request)
    return redirect("login")
