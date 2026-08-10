import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("materials", "0003_historicalmaterial_standard_price_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 発注者フィールド追加
        migrations.AddField(
            model_name="purchaseorder",
            name="ordered_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ordered_purchase_orders",
                to=settings.AUTH_USER_MODEL,
                verbose_name="発注者",
            ),
        ),
        # simple_history の HistoricalPurchaseOrder にも追加
        migrations.AddField(
            model_name="historicalpurchaseorder",
            name="ordered_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="発注者",
            ),
        ),
        # 受領確認フィールド追加
        migrations.AddField(
            model_name="delivery",
            name="received",
            field=models.BooleanField(default=False, verbose_name="受領済み"),
        ),
        migrations.AddField(
            model_name="delivery",
            name="received_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="received_deliveries",
                to=settings.AUTH_USER_MODEL,
                verbose_name="受領者",
            ),
        ),
        migrations.AddField(
            model_name="delivery",
            name="received_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="受領日時"),
        ),
        # 納品書画像・OCRフィールド追加
        migrations.AddField(
            model_name="delivery",
            name="image",
            field=models.ImageField(
                blank=True,
                help_text="納品書の写真・スキャン画像",
                upload_to="deliveries/%Y/%m/",
                verbose_name="納品書画像",
            ),
        ),
        migrations.AddField(
            model_name="delivery",
            name="original_filename",
            field=models.CharField(blank=True, max_length=255, verbose_name="元ファイル名"),
        ),
        migrations.AddField(
            model_name="delivery",
            name="extraction_raw",
            field=models.TextField(
                blank=True,
                help_text="Claude APIによるOCR結果の生テキスト",
                verbose_name="AI読取生データ",
            ),
        ),
    ]
