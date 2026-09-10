"""入札案件に、その案件から作った現場への参照を埋める（ADR-0031）。

これまで積算開始は `EST-<入札案件ID>`、落札は `BID-<入札案件ID>` の現場を作り、
入札案件側に参照を残していなかった。現場コードから辿って紐付ける。

- 片方だけあれば、それを紐付ける
- 両方あれば `BID-`（落札で作った受注済の現場）を紐付ける。`EST-` は消さず、中身にも触らない
- 同じ会社の中でだけ突き合わせる。別の会社の現場は紐付けない
- 既に現場が入っている入札案件には触らない
"""
import re

from django.db import migrations
from django.db.models import Q

_CODE = re.compile(r"(BID|EST)-([1-9][0-9]*)")
# 同じ入札案件に両方あるときは、落札で作った現場を優先する
_PRIORITY = {"BID": 0, "EST": 1}


def link_bid_sites(BidProject, Site):
    """現場が空の入札案件に、現場コードが一致する同じ会社の現場を紐付ける。

    マイグレーションからは履歴モデルを、テストからは実モデルを渡す。
    データ移送は全テナントが対象なので、テナントで絞らない _base_manager を使う。

    Returns:
        紐付けた入札案件の件数
    """
    best = {}  # (company_id, 入札案件ID) → (優先度, 現場ID)
    candidates = Site._base_manager.filter(
        Q(code__startswith="BID-") | Q(code__startswith="EST-"),
    ).values_list("pk", "company_id", "code")
    for site_id, company_id, code in candidates:
        match = _CODE.fullmatch(code)
        if not match:
            continue
        key = (company_id, int(match.group(2)))
        entry = (_PRIORITY[match.group(1)], site_id)
        if key not in best or entry < best[key]:
            best[key] = entry

    linked = 0
    for (company_id, bid_pk), (_priority, site_id) in best.items():
        linked += BidProject._base_manager.filter(
            pk=bid_pk, company_id=company_id, site__isnull=True,
        ).update(site_id=site_id)
    return linked


def forwards(apps, schema_editor):
    link_bid_sites(apps.get_model("bids", "BidProject"), apps.get_model("sites", "Site"))


class Migration(migrations.Migration):

    dependencies = [
        ("bids", "0021_bidproject_site"),
        ("sites", "0005_alter_estimateimport_customer_and_more"),
    ]

    operations = [
        # 逆方向は何もしない。参照列は 0021 を戻せば消え、現場そのものには触っていない。
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
