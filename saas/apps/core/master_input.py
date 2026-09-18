"""候補から選び、無ければその場でマスタに登録する（ADR-0099）。

## なぜ

プルダウンだけの欄は、**マスタに無いものを選ぼうとした時点で作業が止まる。**
「先にマスタ画面で登録してから戻ってくる」という2画面の往復が要り、
現場や積算のように**外の書類を見ながら入れる**画面ではそこで手が止まる。
公告を見ながら積算を始めるときにマスタに無い発注機関が出るのは珍しくない、
というのが発注機関を自由入力にした理由だった（ADR-0080）。同じことが
工種・材料・顧客・発注先・積算品目・現場でも起きている。

そこで入力欄は文字にし、登録済みのものを `<datalist>` で候補に出す。
候補に無い値もそのまま送れて、保存時にこの関数がマスタへ登録する。

## 引き当ては完全一致だけ

表記ゆれを寄せる正規化は**しない**（ADR-0080 と同じ理由）。
「厚木市」と「厚木市教育委員会」は似ていて別物で、寄せると取り違える。

二重登録を防ぐのは**候補の一覧の役目**。打ちかけの文字で既存のものが
出てくるので、同じものを作ってしまう手前で気づける。
ここで似た名前まで拾って寄せると、別物を1つにしてしまう事故のほうが重い。

## コードは自動で採番する

マスタの多くは (company, code) が一意で、コードが要る。人に考えさせると
そこで止まるので、使われていない連番を振る。日報の現場・工種の自動登録
（reports.forms）が既にこの方式で、そちらもここへ寄せた。
"""

from __future__ import annotations


def next_code(queryset, prefix: str) -> str:
    """手入力で新規登録するときのコードを採番する。

    コードは (company, code) で一意なので、重複しない値が要る。
    """
    used = set(queryset.values_list("code", flat=True))
    n = 1
    while f"{prefix}{n:04d}" in used:
        n += 1
    return f"{prefix}{n:04d}"


def name_choices(queryset, field: str = "name") -> list[str]:
    """`<datalist>` に出す候補。重複を除いて並べる。"""
    return sorted({value for value in queryset.values_list(field, flat=True) if value})


def resolve_site(company, name: str, *, created_by=None):
    """現場名から現場を引く。無ければ登録する。"""
    from apps.sites.models import Site

    name = (name or "").strip()
    if not name:
        return None
    # unscoped: company を引数で受けて明示的に絞る（呼び出し側はフォーム）
    site = Site.unscoped.filter(company=company, name=name).first()
    if site:
        return site
    return Site.unscoped.create(  # unscoped: company を明示指定
        company=company, name=name[:200],
        code=next_code(Site.unscoped.filter(company=company), "S"),
        created_by=created_by,
    )


def resolve_work_type(company, name: str, *, created_by=None):
    """工種名から工種を引く。無ければ登録する。"""
    from apps.masters.models import WorkType

    name = (name or "").strip()
    if not name:
        return None
    work_type = WorkType.unscoped.filter(company=company, name=name).first()
    if work_type:
        return work_type
    return WorkType.unscoped.create(  # unscoped: company を明示指定
        company=company, name=name[:100],
        code=next_code(WorkType.unscoped.filter(company=company), "W"),
        created_by=created_by,
    )


def resolve_customer(company, name: str, *, created_by=None):
    """顧客名から顧客を引く。無ければ登録する。"""
    from apps.masters.models import Customer

    name = (name or "").strip()
    if not name:
        return None
    customer = Customer.unscoped.filter(company=company, name=name).first()
    if customer:
        return customer
    return Customer.unscoped.create(  # unscoped: company を明示指定
        company=company, name=name[:200],
        code=next_code(Customer.unscoped.filter(company=company), "C"),
        created_by=created_by,
    )


def resolve_supplier(company, name: str, *, created_by=None):
    """発注先名から発注先を引く。無ければ登録する。"""
    from apps.masters.models import Supplier

    name = (name or "").strip()
    if not name:
        return None
    supplier = Supplier.unscoped.filter(company=company, name=name).first()
    if supplier:
        return supplier
    return Supplier.unscoped.create(  # unscoped: company を明示指定
        company=company, name=name[:200],
        code=next_code(Supplier.unscoped.filter(company=company), "SP"),
        created_by=created_by,
    )


def resolve_material(company, name: str, *, unit: str = "", created_by=None):
    """材料名から材料を引く。無ければ登録する。

    単位は材料マスタの必須項目なので、呼び出し側の欄（積算品目の単位など）から
    受け取る。分からなければ「式」にする。**人に聞き直すと入力が止まる。**
    """
    from apps.materials.models import Material

    name = (name or "").strip()
    if not name:
        return None
    material = Material.unscoped.filter(company=company, name=name).first()
    if material:
        return material
    return Material.unscoped.create(  # unscoped: company を明示指定
        company=company, name=name[:200], unit=(unit or "式")[:20],
        code=next_code(Material.unscoped.filter(company=company), "M"),
        created_by=created_by,
    )


def resolve_estimation_item(company, name: str, *, unit: str = "", created_by=None):
    """積算品目名から品目を引く。無ければ登録する。

    単位は品目マスタの必須項目。内訳書の行から受け取り、無ければ「式」にする。
    """
    from apps.estimation.models import EstimationItem

    name = (name or "").strip()
    if not name:
        return None
    item = EstimationItem.unscoped.filter(company=company, canonical_name=name).first()
    if item:
        return item
    return EstimationItem.unscoped.create(  # unscoped: company を明示指定
        company=company, canonical_name=name[:200], unit=(unit or "式")[:20],
        code=next_code(EstimationItem.unscoped.filter(company=company), "I"),
        created_by=created_by,
    )
