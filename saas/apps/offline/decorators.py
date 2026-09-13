"""圏外保存からの送り直しを受け付けるビューのデコレータ（ADR-0048）。"""

import uuid
from functools import wraps

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect

from apps.offline.models import OfflineSubmission

# 端末の JavaScript が送り直すときに付けるヘッダ。付いていれば画面の代わりに JSON を返す。
RESEND_HEADER = "X-Offline-Resend"

_REDIRECT_CODES = (301, 302, 303, 307, 308)

INVALID_MESSAGE = "入力に誤りがあるため登録できませんでした。画面を開いて入力し直してください。"


def _client_request_id(request):
    try:
        return uuid.UUID(request.POST.get("client_request_id", "").strip())
    except ValueError:
        return None


def _duplicate(request, key, resend):
    # unscoped: 送信者本人の記録を、会社とユーザーで明示的に絞って引く。
    existing = OfflineSubmission.unscoped.filter(
        company=request.user.company, user=request.user, client_request_id=key,
    ).first()
    location = existing.location if existing else ""
    if resend:
        return JsonResponse({"ok": True, "duplicate": True, "location": location})
    messages.info(request, "この入力はすでに登録済みです。")
    return redirect(location or request.path)


def offline_resendable(view):
    """POST に端末の識別番号（client_request_id）が付いていれば、同じ入力の2回目を登録しない。

    - 1回目: ビューをそのまま実行し、登録できた（リダイレクトが返った）ら識別番号を記録する。
      入力に誤りがあった（画面が返った）ら記録しない。直して送り直せるようにするため
    - 2回目以降: ビューを実行せず、1回目の移動先へ戻す
    - 送り直し（ヘッダ X-Offline-Resend: 1）のときは、画面の代わりに JSON を返す。
      端末の JavaScript が結果を読み、登録できたら端末の控えを消すため

    記録の作成とビューの実行を同じトランザクションに入れる。同じ識別番号が同時に届いても、
    一意制約で片方を止める。識別番号が無い・読めない送信は、今までどおりビューをそのまま実行する。
    """

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        key = _client_request_id(request) if request.method == "POST" else None
        if key is None or not getattr(request.user, "company_id", None):
            return view(request, *args, **kwargs)
        resend = request.headers.get(RESEND_HEADER) == "1"

        with transaction.atomic():
            try:
                with transaction.atomic():
                    submission = OfflineSubmission.unscoped.create(
                        company=request.user.company,
                        user=request.user,
                        client_request_id=key,
                        path=request.path,
                        created_by=request.user,
                    )
            except IntegrityError:
                return _duplicate(request, key, resend)

            response = view(request, *args, **kwargs)
            if response.status_code in _REDIRECT_CODES:
                submission.location = response["Location"]
                submission.save(update_fields=["location", "updated_at"])
                if resend:
                    return JsonResponse({"ok": True, "location": submission.location})
                return response

            # 登録できなかった。直して送り直せるよう、記録ごと取り消す
            transaction.set_rollback(True)

        if resend:
            return JsonResponse(
                {"ok": False, "status": response.status_code, "message": INVALID_MESSAGE},
                status=422,
            )
        return response

    wrapped.offline_resendable = True
    return wrapped
