from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import TenantModel


class User(AbstractUser):
    """カスタムユーザー。テナント帰属 + 社員番号。

    ロールは Django Group (admin / manager / worker) で表現する。
    ADR-0002: カスタムユーザーは初回 migrate 前に定義必須。
    """

    company = models.ForeignKey(
        "tenants.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="会社",
    )
    employee_no = models.CharField("社員番号", max_length=50, blank=True)
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="部署",
    )

    class Meta:
        verbose_name = "ユーザー"
        verbose_name_plural = "ユーザー"

    def __str__(self):
        return self.get_full_name() or self.username


class Department(TenantModel):
    """部署。テナントごとに定義。"""

    name = models.CharField("部署名", max_length=100)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "部署"
        verbose_name_plural = "部署"
        unique_together = [("company", "name")]

    def __str__(self):
        return self.name
