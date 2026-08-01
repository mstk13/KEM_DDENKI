"""
テナント分離マネージャ。

CompanyScopedManager: デフォルトマネージャ。contextvar に格納されたテナントで自動フィルタ。
UnscopedManager: フィルタなし。利用箇所は理由をコメントで明記すること。
"""

from django.db import models

from apps.core.tenant_context import get_current_company


class CompanyScopedQuerySet(models.QuerySet):
    def _filter_by_tenant(self):
        company = get_current_company()
        if company is not None:
            return self.filter(company=company)
        return self


class CompanyScopedManager(models.Manager):
    """現在テナントで自動フィルタするデフォルトマネージャ。"""

    def get_queryset(self):
        return CompanyScopedQuerySet(self.model, using=self._db)._filter_by_tenant()


class UnscopedManager(models.Manager):
    """テナントフィルタなし。利用箇所は理由をコメントで明記すること。"""

    pass
