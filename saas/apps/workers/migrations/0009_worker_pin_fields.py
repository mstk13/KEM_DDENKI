from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0008_historicalworker_allowed_apps_worker_allowed_apps"),
    ]

    operations = [
        migrations.AddField(
            model_name="worker",
            name="pin",
            field=models.CharField(blank=True, help_text="4桁の暗証番号（ハッシュ化して保存）", max_length=128, verbose_name="暗証番号"),
        ),
        migrations.AddField(
            model_name="worker",
            name="pin_set",
            field=models.BooleanField(default=False, help_text="初回ログイン後に暗証番号を設定したかどうか", verbose_name="暗証番号設定済み"),
        ),
        # simple_history
        migrations.AddField(
            model_name="historicalworker",
            name="pin",
            field=models.CharField(blank=True, help_text="4桁の暗証番号（ハッシュ化して保存）", max_length=128, verbose_name="暗証番号"),
        ),
        migrations.AddField(
            model_name="historicalworker",
            name="pin_set",
            field=models.BooleanField(default=False, help_text="初回ログイン後に暗証番号を設定したかどうか", verbose_name="暗証番号設定済み"),
        ),
    ]
