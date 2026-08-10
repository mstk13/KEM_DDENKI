import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0001_initial"),
        ("tenants", "0001_initial"),
        ("sites", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIBatchRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="作成日時")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新日時")),
                ("task_type", models.CharField(choices=[
                    ("cost_forecast", "コスト予測"),
                    ("cost_optimization", "コスト最適化提案"),
                    ("schedule_suggest", "工程提案"),
                    ("schedule_risk", "工程リスク分析"),
                    ("general_analysis", "汎用分析"),
                ], max_length=30, verbose_name="タスク種別")),
                ("model_key", models.CharField(default="haiku", max_length=20, verbose_name="モデル")),
                ("status", models.CharField(choices=[
                    ("pending", "待機中"),
                    ("processing", "処理中"),
                    ("completed", "完了"),
                    ("failed", "失敗"),
                ], default="pending", max_length=20, verbose_name="ステータス")),
                ("error_message", models.TextField(blank=True, verbose_name="エラー")),
                ("scheduled_for", models.DateTimeField(blank=True, help_text="翌営業日の朝9時に設定される", null=True, verbose_name="実行予定日時")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.company", verbose_name="会社")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="作成者")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="batch_requests", to=settings.AUTH_USER_MODEL, verbose_name="依頼者")),
                ("result_log", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="batch_request", to="ai.ailog", verbose_name="実行結果ログ")),
                ("site", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="batch_requests", to="sites.site", verbose_name="対象現場")),
            ],
            options={
                "verbose_name": "AIバッチリクエスト",
                "verbose_name_plural": "AIバッチリクエスト",
                "ordering": ["-created_at"],
            },
        ),
    ]
