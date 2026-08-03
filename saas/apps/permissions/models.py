"""
ロールベース権限管理モデル。

Role × Module の組み合わせで can_read / can_write / can_admin を制御する。
社長が権限マトリクス画面から設定を変更でき、ユーザーにロールを付与する。
"""

from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class Role(TenantModel):
    """ロール定義。テナントごとに作成。

    デフォルトロール:
    - president: 社長（全権限）
    - executive: 役員
    - site_manager: 現場担当者
    - office_staff: 事務員
    - partner_worker: 協力会社
    - developer: 開発者
    """

    code = models.CharField(
        "ロールコード",
        max_length=50,
        help_text="例: president, executive, site_manager",
    )
    name = models.CharField("ロール名", max_length=100)
    description = models.TextField("説明", blank=True)
    is_system = models.BooleanField(
        "システムロール",
        default=False,
        help_text="初期セットアップで自動作成されるロール。削除不可。",
    )

    class Meta:
        verbose_name = "ロール"
        verbose_name_plural = "ロール"
        unique_together = [("company", "code")]
        ordering = ["code"]

    def __str__(self):
        return self.name


class ModulePermission(TenantModel):
    """ロール × モジュール の権限マトリクス。"""

    MODULE_CHOICES = [
        ("reports", "日報管理"),
        ("costs", "原価管理"),
        ("materials", "材料管理"),
        ("bids", "入札管理"),
        ("schedules", "工期管理"),
        ("workers", "人材管理"),
        ("devkanri", "開発管理"),
        ("masters", "取引先管理"),
        ("notifications", "通知"),
        ("settings", "設定"),
    ]

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="module_permissions",
        verbose_name="ロール",
    )
    module = models.CharField(
        "モジュール",
        max_length=50,
        choices=MODULE_CHOICES,
    )
    can_read = models.BooleanField("閲覧", default=False)
    can_write = models.BooleanField("編集", default=False)
    can_admin = models.BooleanField("管理", default=False)

    class Meta:
        verbose_name = "モジュール権限"
        verbose_name_plural = "モジュール権限"
        unique_together = [("role", "module")]
        ordering = ["role", "module"]

    def __str__(self):
        perms = []
        if self.can_read:
            perms.append("R")
        if self.can_write:
            perms.append("W")
        if self.can_admin:
            perms.append("A")
        return f"{self.role.name} - {self.get_module_display()} [{'/'.join(perms)}]"


class UserRole(TenantModel):
    """ユーザー × ロール の紐づけ。社長が権限を付与する。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_roles",
        verbose_name="ユーザー",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="user_roles",
        verbose_name="ロール",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_roles",
        verbose_name="権限付与者",
    )

    class Meta:
        verbose_name = "ユーザーロール"
        verbose_name_plural = "ユーザーロール"
        unique_together = [("user", "role")]

    def __str__(self):
        return f"{self.user} → {self.role.name}"
