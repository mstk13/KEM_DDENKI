"""
共通基底モデル。全アプリのモデルはここから継承する。

- TimeStampedModel: created_at / updated_at / created_by
- TenantModel: TimeStampedModel + company FK（テナント帰属の強制）
"""

from django.conf import settings
from django.db import models

from apps.core.managers import CompanyScopedManager, UnscopedManager


class TimeStampedModel(models.Model):
    """全モデル共通の監査フィールド。"""

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="作成者",
    )

    class Meta:
        abstract = True


class TenantModel(TimeStampedModel):
    """テナント帰属を持つ全モデルの基底。

    company FK を強制し、CompanyScopedManager をデフォルトマネージャとする。
    """

    company = models.ForeignKey(
        "tenants.Company",
        on_delete=models.CASCADE,
        verbose_name="会社",
    )

    objects = CompanyScopedManager()
    unscoped = UnscopedManager()

    class Meta:
        abstract = True
