import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render

from apps.ai.models import AIFeedback, AILog
from apps.sites.models import Site

logger = logging.getLogger(__name__)


@login_required
def ai_log_list(request):
    """AI実行ログ一覧。タスク種別・モデルでフィルタ可能。"""
    logs = AILog.objects.select_related("site", "requested_by").order_by(
        "-created_at"
    )

    task_type = request.GET.get("task_type")
    if task_type:
        logs = logs.filter(task_type=task_type)

    model_used = request.GET.get("model_used")
    if model_used:
        logs = logs.filter(model_used=model_used)

    logs = logs[:100]

    return render(request, "ai/log_list.html", {
        "logs": logs,
        "task_type_choices": AILog.TaskType.choices,
        "model_choices": AILog.ModelType.choices,
        "selected_task_type": task_type,
        "selected_model": model_used,
    })


@login_required
def ai_feedback_create(request, pk):
    """AI出力へのフィードバック登録。"""
    ai_log = get_object_or_404(AILog, pk=pk)

    if request.method == "POST":
        rating = int(request.POST.get("rating", 3))
        is_adopted = request.POST.get("is_adopted") == "on"
        comment = request.POST.get("comment", "")

        AIFeedback.objects.update_or_create(
            ai_log=ai_log,
            defaults={
                "company": ai_log.company,
                "rating": rating,
                "is_adopted": is_adopted,
                "comment": comment,
                "rated_by": request.user,
                "created_by": request.user,
            },
        )
        messages.success(request, "フィードバックを記録しました。")
        return redirect("ai:log_list")

    return render(request, "ai/feedback_form.html", {"ai_log": ai_log})


@login_required
def ai_dashboard(request):
    """AI利用状況ダッシュボード。月次コスト・利用頻度・評価を表示。"""
    # 月間使用量サマリ
    from apps.ai.services.cost_monitor import get_monthly_cost_jpy
    budget_summary = get_monthly_cost_jpy(request.user.company)

    # 月別利用統計
    monthly_stats = list(
        AILog.objects.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            call_count=Count("id"),
            total_cost=Sum("cost_usd"),
            avg_latency=Avg("latency_ms"),
        )
        .order_by("-month")[:12]
    )

    # タスク種別ごとの統計
    task_stats = list(
        AILog.objects.values("task_type")
        .annotate(
            call_count=Count("id"),
            total_cost=Sum("cost_usd"),
            avg_latency=Avg("latency_ms"),
        )
        .order_by("-call_count")
    )

    # フィードバック統計
    feedback_stats = AIFeedback.objects.aggregate(
        avg_rating=Avg("rating"),
        total_feedbacks=Count("id"),
        adopted_count=Count("id", filter=Q(is_adopted=True)),
    )

    return render(request, "ai/dashboard.html", {
        "monthly_stats": monthly_stats,
        "task_stats": task_stats,
        "feedback_stats": feedback_stats,
        "budget_summary": budget_summary,
    })


@login_required
def cost_report(request):
    """APIコスト詳細レポート。タスク別・モデル別・日別・ユーザー別のグラフ付き。"""
    import json as json_mod
    from apps.ai.services.cost_monitor import get_monthly_cost_jpy, get_monthly_cost_report

    budget_summary = get_monthly_cost_jpy(request.user.company)
    report = get_monthly_cost_report(request.user.company)

    # Chart.js用のデータを構築
    # 日別推移
    daily_chart = {
        "labels": [row["date"].strftime("%m/%d") for row in report["by_date"]],
        "data": [row["total_jpy"] for row in report["by_date"]],
    }

    # タスク種別ドーナツチャート
    task_chart = {
        "labels": [row["task_display"] for row in report["by_task"]],
        "data": [row["total_jpy"] for row in report["by_task"]],
    }

    # モデル別ドーナツチャート
    model_chart = {
        "labels": [row["model_display"] for row in report["by_model"]],
        "data": [row["total_jpy"] for row in report["by_model"]],
    }

    # ユーザー別棒グラフ
    user_chart = {
        "labels": [row["user_display"] for row in report["by_user"]],
        "data": [row["total_jpy"] for row in report["by_user"]],
    }

    return render(request, "ai/cost_report.html", {
        "budget_summary": budget_summary,
        "report": report,
        "daily_chart_json": json_mod.dumps(daily_chart, ensure_ascii=False),
        "task_chart_json": json_mod.dumps(task_chart, ensure_ascii=False),
        "model_chart_json": json_mod.dumps(model_chart, ensure_ascii=False),
        "user_chart_json": json_mod.dumps(user_chart, ensure_ascii=False),
    })


@login_required
def cost_prediction(request, site_id):
    """現場のコスト予測結果を表示する。"""
    site = get_object_or_404(Site, pk=site_id)

    # テナント分離チェック
    if site.company != request.user.company:
        messages.error(request, "この現場にアクセスする権限がありません。")
        return redirect("costs:list")

    prediction = None
    error_message = None

    try:
        from apps.ai.services.ml_predictor import HAS_LGBM, CostPredictor

        if not HAS_LGBM:
            error_message = (
                "LightGBM がインストールされていません。"
                "管理者に連絡してください。"
            )
        else:
            predictor = CostPredictor()
            prediction = predictor.predict(site, user=request.user)
            if prediction is None:
                error_message = (
                    "コスト予測モデルがまだ学習されていません。"
                    "管理者に学習の実行を依頼してください。"
                )
    except Exception:
        logger.exception("コスト予測でエラーが発生しました: site=%s", site.name)
        error_message = "予測処理中にエラーが発生しました。"

    # テンプレート表示用にパーセント変換した値を追加
    display_prediction = None
    if prediction:
        display_prediction = {
            **prediction,
            "consumption_ratio_pct": round(
                prediction["predicted_consumption_ratio"] * 100, 1
            ),
            "overrun_probability_pct": round(
                prediction["overrun_probability"] * 100, 1
            ),
        }

    # 特徴量重要度の正規化（バーチャート表示用）
    importance_items = []
    if prediction and prediction.get("feature_importance"):
        max_importance = max(prediction["feature_importance"].values())
        if max_importance > 0:
            importance_items = [
                {
                    "name": _feature_display_name(k),
                    "value": v,
                    "pct": round(v / max_importance * 100, 1),
                }
                for k, v in prediction["feature_importance"].items()
            ]

    return render(request, "ai/cost_prediction.html", {
        "site": site,
        "prediction": display_prediction,
        "error_message": error_message,
        "importance_items": importance_items,
    })


def _feature_display_name(key):
    """特徴量キーを日本語表示名に変換する。"""
    names = {
        "contract_amount": "受注金額",
        "duration_days": "工期日数",
        "elapsed_days": "経過日数",
        "elapsed_ratio": "工期進捗率",
        "budget_total": "予算合計",
        "budget_item_count": "予算項目数",
        "cost_total": "実績合計",
        "cost_transaction_count": "原価データ数",
        "consumption_ratio": "消化率",
        "daily_burn": "日次消化額",
        "recent_daily_burn": "直近7日消化額",
        "burn_acceleration": "消化加速度",
        "total_work_hours": "総労働時間",
        "overtime_ratio": "残業比率",
        "worker_count": "作業員数",
        "report_count": "日報数",
        "process_count": "工程数",
        "delay_ratio": "遅延率",
    }
    if key.startswith("ratio_"):
        code = key.replace("ratio_", "")
        return f"{code}比率"
    return names.get(key, key)


def _check_site_access(request, site):
    """テナント分離チェック。アクセス不可なら redirect を返す。"""
    if site.company != request.user.company:
        messages.error(request, "この現場にアクセスする権限がありません。")
        return redirect("costs:list")
    return None


def _llm_availability():
    """LLM機能が使えるか（APIキー登録済みか）を返す。"""
    from apps.ai.services.llm_advisor import check_availability

    return check_availability()


@login_required
def ai_site_select(request):
    """AI機能を実行する現場を選ぶ画面。

    コスト分析・工程提案は現場単位のため、サイドバーからは
    この画面を経由して各機能に入る。
    """
    sites = Site.objects.select_related("customer").order_by("-created_at")
    available, unavailable_message = _llm_availability()

    return render(request, "ai/site_select.html", {
        "sites": sites,
        "llm_available": available,
        "llm_unavailable_message": unavailable_message,
    })


@login_required
def cost_optimization(request, site_id):
    """コスト最適化提案を表示する。"""
    site = get_object_or_404(Site, pk=site_id)
    denied = _check_site_access(request, site)
    if denied:
        return denied

    result = None
    error_message = None
    model_key = request.GET.get("model", "haiku")
    available, unavailable_message = _llm_availability()

    # 17時以降チェック
    from apps.ai.services.batch_handler import is_after_hours
    after_hours = is_after_hours()

    if request.method == "POST":
        # バッチ処理を選択した場合
        if request.POST.get("batch") == "1":
            from apps.ai.services.batch_handler import create_batch_request
            batch = create_batch_request(
                request.user.company, site, "cost_optimization",
                request.POST.get("model", "haiku"), request.user,
            )
            messages.success(
                request,
                f"バッチ処理を予約しました（{batch.scheduled_for:%m/%d %H:%M} 実行予定）。"
                "結果は通知でお知らせします。",
            )
            return redirect("ai:batch_list")

        if not available:
            error_message = unavailable_message
        else:
            try:
                from apps.ai.services.llm_advisor import get_cost_optimization

                # ML予測結果があれば取得
                ml_prediction = None
                try:
                    from apps.ai.services.ml_predictor import HAS_LGBM, CostPredictor

                    if HAS_LGBM:
                        predictor = CostPredictor()
                        ml_prediction = predictor.predict(site, user=request.user)
                except Exception:
                    logger.info("ML予測は利用不可（スキップ）")

                model_key = request.POST.get("model", "haiku")
                result = get_cost_optimization(
                    site,
                    user=request.user,
                    model_key=model_key,
                    prediction=ml_prediction,
                )
                if result["parsed"] is None:
                    error_message = "AIの応答を解析できませんでした。生テキストを表示します。"

            except ValueError as e:
                error_message = str(e)
            except Exception:
                logger.exception("コスト最適化提案でエラー: site=%s", site.name)
                error_message = "処理中にエラーが発生しました。"

    return render(request, "ai/cost_optimization.html", {
        "site": site,
        "result": result,
        "error_message": error_message,
        "model_key": model_key,
        "llm_available": available,
        "llm_unavailable_message": unavailable_message,
        "after_hours": after_hours,
    })


@login_required
def schedule_suggestion(request, site_id):
    """工程提案を表示する。"""
    site = get_object_or_404(Site, pk=site_id)
    denied = _check_site_access(request, site)
    if denied:
        return denied

    result = None
    error_message = None
    model_key = request.GET.get("model", "haiku")
    available, unavailable_message = _llm_availability()

    from apps.ai.services.batch_handler import is_after_hours
    after_hours = is_after_hours()

    if request.method == "POST":
        if request.POST.get("batch") == "1":
            from apps.ai.services.batch_handler import create_batch_request
            batch = create_batch_request(
                request.user.company, site, "schedule_suggest",
                request.POST.get("model", "haiku"), request.user,
            )
            messages.success(request, f"バッチ処理を予約しました（{batch.scheduled_for:%m/%d %H:%M} 実行予定）。")
            return redirect("ai:batch_list")

        if not available:
            error_message = unavailable_message
        else:
            try:
                from apps.ai.services.llm_advisor import get_schedule_suggestion

                model_key = request.POST.get("model", "haiku")
                result = get_schedule_suggestion(
                    site, user=request.user, model_key=model_key,
                )
                if result["parsed"] is None:
                    error_message = "AIの応答を解析できませんでした。生テキストを表示します。"

            except ValueError as e:
                error_message = str(e)
            except Exception:
                logger.exception("工程提案でエラー: site=%s", site.name)
                error_message = "処理中にエラーが発生しました。"

    return render(request, "ai/schedule_suggestion.html", {
        "site": site,
        "result": result,
        "error_message": error_message,
        "model_key": model_key,
        "llm_available": available,
        "llm_unavailable_message": unavailable_message,
        "after_hours": after_hours,
    })


@login_required
def schedule_risk(request, site_id):
    """工程リスク分析を表示する。"""
    site = get_object_or_404(Site, pk=site_id)
    denied = _check_site_access(request, site)
    if denied:
        return denied

    result = None
    error_message = None
    model_key = request.GET.get("model", "haiku")
    available, unavailable_message = _llm_availability()

    from apps.ai.services.batch_handler import is_after_hours
    after_hours = is_after_hours()

    if request.method == "POST":
        if request.POST.get("batch") == "1":
            from apps.ai.services.batch_handler import create_batch_request
            batch = create_batch_request(
                request.user.company, site, "schedule_risk",
                request.POST.get("model", "haiku"), request.user,
            )
            messages.success(request, f"バッチ処理を予約しました（{batch.scheduled_for:%m/%d %H:%M} 実行予定）。")
            return redirect("ai:batch_list")

        if not available:
            error_message = unavailable_message
        else:
            try:
                from apps.ai.services.llm_advisor import get_schedule_risk_analysis

                model_key = request.POST.get("model", "haiku")
                result = get_schedule_risk_analysis(
                    site, user=request.user, model_key=model_key,
                )
                if result["parsed"] is None:
                    error_message = "AIの応答を解析できませんでした。生テキストを表示します。"

            except ValueError as e:
                error_message = str(e)
            except Exception:
                logger.exception("工程リスク分析でエラー: site=%s", site.name)
                error_message = "処理中にエラーが発生しました。"

    return render(request, "ai/schedule_risk.html", {
        "site": site,
        "result": result,
        "error_message": error_message,
        "model_key": model_key,
        "llm_available": available,
        "llm_unavailable_message": unavailable_message,
        "after_hours": after_hours,
    })


@login_required
def batch_list(request):
    """AIバッチリクエスト一覧。"""
    from apps.ai.models import AIBatchRequest

    batches = AIBatchRequest.objects.select_related(
        "site", "requested_by", "result_log",
    ).order_by("-created_at")[:50]

    return render(request, "ai/batch_list.html", {"batches": batches})
