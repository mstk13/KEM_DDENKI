# CLAUDE.md — SaaS版 開発規律

本ファイルは Claude Code への入力として使用する。SPEC.md 第10章の開発規律を実装時に参照しやすい形でまとめたもの。

## 絶対ルール

1. **Django 5.2 LTS / Python 3.12** を変更しない。依存追加は ADR 必須
2. **業種名をコード・クラス名・分岐に書かない**。業種差異は WorkType マスタで表現する
3. **テナント帰属モデルは TenantModel を継承**し、CompanyScopedManager を通す。unscoped の使用は理由をコメントで明記
4. **新規モデルには simple-history を付与**し、admin 登録・テナント越境テスト・マイグレーションを同一PRに含める
5. **予算・原価に触れるコードは、工種 × 原価区分の粒度を崩さない**。粒度を落とす変更は禁止
6. **main へ直接コミットしない**。PR + CI green + レビュー1名
7. **マイグレーションは expand/contract**。破壊的変更を単一リリースで行わない
8. **金額計算は Decimal のみ**。float 禁止。タイムゾーンは USE_TZ=True 前提で aware datetime のみ
9. **設計判断をしたら docs/saas/adr/ に1ファイル追加**する

## プロジェクト構造

```
saas/
├── config/          … Django 設定 (settings.py, urls.py, wsgi.py)
├── apps/
│   ├── core/        … 共通基盤 (TenantModel, CompanyScopedManager, middleware)
│   ├── tenants/     … Company, CompanyApp
│   ├── accounts/    … User (カスタム), Department
│   ├── masters/     … WorkType, CostCategory, Customer, Supplier, WorkStandard
│   ├── workers/     … JobTitle, Position, Worker, WorkerEvaluation     [M5]
│   ├── sites/       … Site, Process                                    [M2]
│   ├── materials/   … Material, PurchaseOrder, PurchaseOrderItem       [M4]
│   ├── reports/     … DailyReport, DailyReportMaterial                 [M2]
│   └── costs/       … BudgetItem, CostTransaction, services.py        [M3]
├── tests/           … テスト (越境テスト必須, 32件)
├── Dockerfile
├── docker-compose.yml
└── manage.py
```

## Docker で起動

```bash
cd saas
cp .env.example .env   # 値を編集
docker compose up -d   # PostgreSQL + Django
```

## テスト

```bash
cd saas
source .venv/bin/activate
USE_SQLITE=true python -m pytest tests/ -v
```

## テナント分離の使い方

```python
# モデル定義 — TenantModel を継承するだけで company FK + CompanyScopedManager が付く
from apps.core.models import TenantModel

class MyModel(TenantModel):
    name = models.CharField(max_length=200)
    # company は TenantModel が自動的に持つ

# クエリ — objects は自動的にテナントフィルタされる
MyModel.objects.all()         # → 現在テナントのデータのみ
MyModel.unscoped.all()        # → 全テナント（理由をコメントで明記）

# ビュー — @app_required でアプリ有効化チェック
from apps.core.decorators import app_required

@app_required("nippou")
def my_view(request):
    ...
```
