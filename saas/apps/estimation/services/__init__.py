"""積算サービス層。承認・却下のファサード。"""

from django.utils import timezone


def approve_alias(alias, user):
    """名寄せを承認する。"""
    alias.status = alias.Status.APPROVED
    alias.reviewed_by = user
    alias.reviewed_at = timezone.now()
    alias.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    return alias


def reject_alias(alias, user):
    """名寄せを却下する。"""
    alias.status = alias.Status.REJECTED
    alias.reviewed_by = user
    alias.reviewed_at = timezone.now()
    alias.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    return alias


def approve_item(item, user):
    """品目を承認する。"""
    item.status = item.Status.APPROVED
    item.save(update_fields=["status", "updated_at"])
    return item
