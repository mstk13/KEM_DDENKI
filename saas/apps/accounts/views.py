import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
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


def _hash_pin(pin):
    """暗証番号をハッシュ化する。"""
    return hashlib.sha256(pin.encode()).hexdigest()


def _verify_pin(worker, pin):
    """暗証番号を検証する。"""
    return worker.pin == _hash_pin(pin)


def check_employee_code(request):
    """社員番号の存在チェックAPI。暗証番号設定状況も返す。"""
    code = request.GET.get("code", "").strip()
    if not code:
        return JsonResponse({"found": False})

    worker = _find_worker_by_code(code)
    if not worker:
        return JsonResponse({"found": False})

    return JsonResponse({
        "found": True,
        "name": worker.name,
        "needs_pin": _is_president_worker(worker) or worker.pin_set,
        "is_first_login": not worker.pin_set and not _is_president_worker(worker),
    })


def employee_login(request):
    """社員番号ベースのログイン。

    フロー:
    1. 初回ログイン: 社員番号のみ → ログイン後に暗証番号設定画面へ
    2. 暗証番号設定済み: 社員番号 + 4桁暗証番号
    3. 社長: 社員番号 + 管理者パスワード
    """
    error = ""

    if request.method == "POST":
        code = request.POST.get("employee_code", "").strip()
        pin = request.POST.get("pin", "").strip()

        worker = _find_worker_by_code(code)

        if not worker:
            error = "この社員番号は登録されていません"
        elif _is_president_worker(worker):
            # 社長: 管理者パスワードで認証
            if not pin:
                error = "管理者パスワードを入力してください"
            elif pin != settings.PRESIDENT_PIN:
                error = "管理者パスワードが正しくありません"
            else:
                user = _get_or_create_user(worker)
                set_current_company(worker.company)
                login(request, user)
                return redirect("dashboard")
        elif worker.pin_set:
            # 暗証番号設定済み: 暗証番号で認証
            if not pin:
                error = "暗証番号を入力してください"
            elif not _verify_pin(worker, pin):
                error = "暗証番号が正しくありません"
            else:
                user = _get_or_create_user(worker)
                set_current_company(worker.company)
                login(request, user)
                return redirect("dashboard")
        else:
            # 初回ログイン: 社員番号のみでログイン → 暗証番号設定へ
            user = _get_or_create_user(worker)
            set_current_company(worker.company)
            login(request, user)
            return redirect("setup_pin")

    return render(request, "registration/login.html", {"error": error})


@login_required
def setup_pin(request):
    """初回ログイン後の暗証番号設定画面。"""
    worker = getattr(request.user, "worker_profile", None)
    if not worker:
        messages.error(request, "作業員情報が見つかりません。")
        return redirect("dashboard")

    if worker.pin_set:
        return redirect("dashboard")

    error = ""
    if request.method == "POST":
        pin1 = request.POST.get("pin", "").strip()
        pin2 = request.POST.get("pin_confirm", "").strip()

        if not pin1 or len(pin1) != 4 or not pin1.isdigit():
            error = "4桁の数字を入力してください"
        elif pin1 != pin2:
            error = "暗証番号が一致しません"
        else:
            worker.pin = _hash_pin(pin1)
            worker.pin_set = True
            worker.save(update_fields=["pin", "pin_set"])
            messages.success(
                request,
                "暗証番号を設定しました。次回から社員番号と暗証番号でログインしてください。",
            )
            return redirect("dashboard")

    return render(request, "registration/setup_pin.html", {
        "error": error,
        "worker": worker,
    })


@login_required
def change_pin(request):
    """暗証番号の変更。"""
    worker = getattr(request.user, "worker_profile", None)
    if not worker:
        messages.error(request, "作業員情報が見つかりません。")
        return redirect("dashboard")

    error = ""
    if request.method == "POST":
        current = request.POST.get("current_pin", "").strip()
        new_pin = request.POST.get("new_pin", "").strip()
        confirm = request.POST.get("new_pin_confirm", "").strip()

        if worker.pin_set and not _verify_pin(worker, current):
            error = "現在の暗証番号が正しくありません"
        elif not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
            error = "4桁の数字を入力してください"
        elif new_pin != confirm:
            error = "新しい暗証番号が一致しません"
        else:
            worker.pin = _hash_pin(new_pin)
            worker.pin_set = True
            worker.save(update_fields=["pin", "pin_set"])
            messages.success(request, "暗証番号を変更しました。")
            return redirect("dashboard")

    return render(request, "registration/change_pin.html", {
        "error": error,
        "worker": worker,
    })


def employee_logout(request):
    """ログアウト。セッションを完全にクリアしてログイン画面へ。"""
    logout(request)
    return redirect("login")
