# 電機屋 業務管理アプリ — DB設計書

**作成日**: 2026-08-03
**最終更新**: 2026-08-03
**前提**: PostgreSQL（リレーショナルDB）を想定。Django ORM + django-simple-history。マルチテナント（company_id による行レベル分離）。

---

## ER図（概要）

```
┌────────────┐
│  Company   │─────────────── テナント（全テーブルの親）
└─────┬──────┘
      │
      ├──< CompanyApp       利用アプリ設定
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 ユーザー・権限系                            │
      │  │  ┌──────┐   ┌────────────┐   ┌──────┐                    │
      │  ├─<│ User │──<│  UserRole  │>──│ Role │                    │
      │  │  └──┬───┘   └────────────┘   └──┬───┘                    │
      │  │     │                           │                         │
      │  │     │ ┌────────────┐    ┌───────┴──────────────┐          │
      │  │     └<│ Department │    │ ModulePermission     │          │
      │  │       └────────────┘    └──────────────────────┘          │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 現場・工期系                                │
      │  │  ┌──────┐   ┌─────────┐   ┌────────────┐                 │
      │  ├─<│ Site │──<│ Process │   │   Phase    │                 │
      │  │  └──┬───┘   └─────────┘   └────────────┘                 │
      │  │     │   ┌────────────┐   ┌────────────┐                   │
      │  │     ├──<│ Milestone  │   │ Assignment │                   │
      │  │     │   └────────────┘   └────────────┘                   │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 日報系                                     │
      │  │  ┌─────────────┐   ┌───────────────────────┐              │
      │  ├─<│ DailyReport │──<│ DailyReportMaterial   │              │
      │  │  └─────────────┘   └───────────────────────┘              │
      │  │  ┌────────────────┐   ┌───────────────┐                   │
      │  │  │ SafetyTemplate │──<│ SafetyRecord  │                   │
      │  │  └────────────────┘   └───────────────┘                   │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 原価系                                     │
      │  │  ┌────────────┐   ┌─────────────────┐                     │
      │  ├─<│ BudgetItem │   │ CostTransaction │                     │
      │  │  └────────────┘   └─────────────────┘                     │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 材料系                                     │
      │  │  ┌──────────┐  ┌───────────────┐  ┌───────────────────┐   │
      │  ├─<│ Material │  │ PurchaseOrder │─<│ PurchaseOrderItem │   │
      │  │  └──────────┘  └───────────────┘  └───────────────────┘   │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 入札系                                     │
      │  │  ┌────────────┐  ┌──────────┐  ┌───────────────┐          │
      │  ├─<│ BidProject │─<│ BidCost  │  │ BidCompetitor │          │
      │  │  └────────────┘  └──────────┘  └───────────────┘          │
      │  │  ┌──────────────┐  ┌───────────┐  ┌───────────────┐       │
      │  │  │ ScrapeTarget │  │ UnitPrice │  │ Qualification │       │
      │  │  └──────────────┘  └───────────┘  └───────────────┘       │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 人材系                                     │
      │  │  ┌────────┐  ┌──────────┐  ┌──────────┐                   │
      │  ├─<│ Worker │  │ JobTitle │  │ Position │                   │
      │  │  └──┬─────┘  └──────────┘  └──────────┘                   │
      │  │     ├──<┌─────────────────────┐                            │
      │  │     │   │ WorkerQualification │                            │
      │  │     │   └─────────────────────┘                            │
      │  │     ├──<┌───────────────┐                                  │
      │  │     │   │ HealthCheckup │                                  │
      │  │     │   └───────────────┘                                  │
      │  │     ├──<┌──────────────────┐                               │
      │  │         │ WorkerEvaluation │                               │
      │  │         └──────────────────┘                               │
      │  │  ┌──────────────────────┐                                  │
      │  │  │ EvaluationTemplate   │                                  │
      │  │  └──────────────────────┘                                  │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 取引先・マスタ系                             │
      │  │  ┌──────────┐  ┌──────────────┐  ┌──────────┐             │
      │  ├─<│ WorkType │  │ CostCategory │  │ Customer │             │
      │  │  └──────────┘  └──────────────┘  └──────────┘             │
      │  │  ┌──────────┐  ┌──────────────┐                            │
      │  │  │ Supplier │  │ WorkStandard │                            │
      │  │  └──────────┘  └──────────────┘                            │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 開発管理系                                  │
      │  │  ┌────────────┐  ┌──────────┐  ┌────────────┐             │
      │  ├─<│ DevProject │─<│ DevTask  │─<│ DevComment │             │
      │  │  └────────────┘  └──────────┘  └────────────┘             │
      │  └───────────────────────────────────────────────────────────┘
      │
      │  ┌───────────────────────────────────────────────────────────┐
      │  │                 通知系                                     │
      │  │  ┌──────────────┐  ┌───────────┐  ┌──────────┐            │
      │  ├─<│ Notification │  │ AlertRule │─<│ AlertLog │            │
      │  │  └──────────────┘  └───────────┘  └──────────┘            │
      │  └───────────────────────────────────────────────────────────┘
```

---

## テーブル定義

### 共通カラム規約

テナントスコープの全テーブル（Company 自身を除く）に以下の共通カラムを含む（以降の個別定義では省略）:

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | BigAutoField | PRIMARY KEY | Django 自動採番 |
| created_at | DateTimeField | NOT NULL, auto_now_add | 作成日時 |
| updated_at | DateTimeField | NOT NULL, auto_now | 更新日時 |
| created_by_id | ForeignKey → User | NULL | 作成者 |
| company_id | ForeignKey → Company | NOT NULL | テナント |

> **注**: User テーブルは Django AbstractUser を継承しており、id / password / last_login / is_superuser / date_joined 等は Django 標準カラム。company_id は User にも存在する（テナント紐付け）。

---

### A. テナント

#### A1. Company — 会社（テナント）

Djangoアプリ: `tenants`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | BigAutoField | PK | — |
| created_at | DateTimeField | NOT NULL | 作成日時 |
| updated_at | DateTimeField | NOT NULL | 更新日時 |
| created_by_id | ForeignKey → User | NULL | 作成者 |
| name | CharField | NOT NULL | 会社名 |
| industry_type | CharField | | 業種（参考情報） |
| contract_plan | CharField | NOT NULL | 契約プラン |
| is_active | BooleanField | DEFAULT true | 有効 |

#### A2. CompanyApp — 会社別アプリ設定

Djangoアプリ: `tenants`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| company_id | ForeignKey → Company | NOT NULL | 会社 |
| app_code | CharField | NOT NULL | アプリコード: jinzai, hyoka, koutei, zairyo, nippou, genka |
| is_enabled | BooleanField | DEFAULT true | 有効 |
| enabled_at | DateTimeField | NULL | 有効化日時 |

---

### B. ユーザー・権限

#### B1. User — ユーザー

Djangoアプリ: `accounts`（AbstractUser 継承）

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | BigAutoField | PK | — |
| password | CharField | NOT NULL | ハッシュ化パスワード |
| last_login | DateTimeField | NULL | 最終ログイン |
| is_superuser | BooleanField | DEFAULT false | スーパーユーザー権限 |
| username | CharField | UNIQUE, NOT NULL | ユーザー名 |
| first_name | CharField | | 名 |
| last_name | CharField | | 姓 |
| email | EmailField | | メールアドレス |
| is_staff | BooleanField | DEFAULT false | スタッフ権限 |
| is_active | BooleanField | DEFAULT true | 有効 |
| date_joined | DateTimeField | NOT NULL | 登録日 |
| company_id | ForeignKey → Company | NULL | 会社 |
| employee_no | CharField | | 社員番号 |
| department_id | ForeignKey → Department | NULL | 部署 |

#### B2. Department — 部署

Djangoアプリ: `accounts`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | 部署名 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### B3. Role — ロール定義

Djangoアプリ: `permissions`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | ロールコード |
| name | CharField | NOT NULL | ロール名 |
| description | TextField | | 説明 |
| is_system | BooleanField | DEFAULT false | システムロール（削除不可） |

#### B4. ModulePermission — モジュール別権限

Djangoアプリ: `permissions`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| role_id | ForeignKey → Role | NOT NULL | ロール |
| module | CharField | NOT NULL | モジュール: reports, costs, materials, bids, schedules, workers, devkanri, masters, notifications, settings |
| can_read | BooleanField | DEFAULT false | 閲覧 |
| can_write | BooleanField | DEFAULT false | 編集 |
| can_admin | BooleanField | DEFAULT false | 管理 |

#### B5. UserRole — ユーザー×ロール

Djangoアプリ: `permissions`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | ForeignKey → User | NOT NULL | ユーザー |
| role_id | ForeignKey → Role | NOT NULL | ロール |
| granted_by_id | ForeignKey → User | NULL | 権限付与者 |

---

### C. 現場・工期

#### C1. Site — 現場

Djangoアプリ: `sites`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | 現場コード |
| name | CharField | NOT NULL | 現場名 |
| customer_id | ForeignKey → Customer | NULL | 得意先 |
| address | TextField | | 住所 |
| status | CharField | NOT NULL | 状態: estimating, ordered, in_progress, completed, billed, cancelled |
| contract_amount | DecimalField | | 受注金額 |
| start_date | DateField | NULL | 工期開始 |
| end_date | DateField | NULL | 工期終了 |
| manager_id | ForeignKey → Worker | NULL | 現場担当者 |

#### C2. Process — 工程（現場×工種）

Djangoアプリ: `sites`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| work_type_id | ForeignKey → WorkType | NOT NULL | 工種 |
| name | CharField | NOT NULL | 工程名 |
| planned_start | DateField | NULL | 計画開始日 |
| planned_end | DateField | NULL | 計画終了日 |
| actual_start | DateField | NULL | 実績開始日 |
| actual_end | DateField | NULL | 実績終了日 |
| status | CharField | NOT NULL | 状態: planned, in_progress, completed, delayed |
| display_order | IntegerField | DEFAULT 0 | 表示順 |

#### C3. Phase — 工程（ガントチャート用）

Djangoアプリ: `schedules`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| name | CharField | NOT NULL | 工程名 |
| start_date | DateField | NULL | 開始日 |
| end_date | DateField | NULL | 終了日 |
| progress | IntegerField | DEFAULT 0 | 進捗(%) |
| sort_order | IntegerField | DEFAULT 0 | 表示順 |
| color | CharField | | 色（ガントバー色） |
| memo | TextField | | メモ |

#### C4. Milestone — マイルストーン

Djangoアプリ: `schedules`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| name | CharField | NOT NULL | マイルストーン名 |
| target_date | DateField | NULL | 目標日 |
| completed | BooleanField | DEFAULT false | 完了 |
| memo | TextField | | メモ |

#### C5. Assignment — 配置管理

Djangoアプリ: `schedules`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| worker_id | ForeignKey → Worker | NOT NULL | 作業員 |
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| start_date | DateField | NOT NULL | 開始日 |
| end_date | DateField | NULL | 終了日 |
| memo | TextField | | メモ |

---

### D. 日報

#### D1. DailyReport — 日報

Djangoアプリ: `reports`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| worker_id | ForeignKey → Worker | NOT NULL | 作業員 |
| report_date | DateField | NOT NULL | 日付 |
| weather | CharField | | 天候: sunny, cloudy, rainy, snowy, other |
| process_id | ForeignKey → Process | NULL | 工程 |
| work_type_id | ForeignKey → WorkType | NOT NULL | 工種 |
| work_description | TextField | | 作業内容 |
| start_time | TimeField | NULL | 開始時間 |
| end_time | TimeField | NULL | 終了時間 |
| work_hours | DecimalField | | 作業時間 |
| regular_hours | DecimalField | NULL | 通常時間 |
| overtime_hours | DecimalField | | 残業時間 |
| is_partner_worker | BooleanField | DEFAULT false | 協力会社の作業員 |
| partner_id | ForeignKey → Supplier | NULL | 協力会社 |
| memo | TextField | | その他 |
| status | CharField | NOT NULL | 状態: draft, submitted, approved |
| approved_by_id | ForeignKey → User | NULL | 承認者 |
| approved_at | DateTimeField | NULL | 承認日時 |

#### D2. DailyReportMaterial — 日報の使用材料

Djangoアプリ: `reports`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| daily_report_id | ForeignKey → DailyReport | NOT NULL | 日報 |
| material_id | ForeignKey → Material | NULL | 材料（マスタ） |
| material_name | CharField | | 材料名（自由入力） |
| quantity_used | DecimalField | | 使用数量 |
| unit | CharField | | 単位 |

#### D3. SafetyTemplate — 安全書類ひな型

Djangoアプリ: `reports`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| name | CharField | NOT NULL | 書類名（KY活動記録、TBM記録 等） |
| template_file | FileField | | ひな型ファイル |
| is_daily_required | BooleanField | DEFAULT true | 毎日必須 |

#### D4. SafetyRecord — 安全書類の記入チェック

Djangoアプリ: `reports`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| template_id | ForeignKey → SafetyTemplate | NOT NULL | ひな型 |
| worker_id | ForeignKey → Worker | NOT NULL | 作業員 |
| record_date | DateField | NOT NULL | 記入日 |
| completed | BooleanField | DEFAULT false | 記入済み |
| completed_at | DateTimeField | NULL | 記入完了日時 |
| alerted | BooleanField | DEFAULT false | アラート送信済み |

---

### E. 原価管理

#### E1. BudgetItem — 予算項目

Djangoアプリ: `costs`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| work_type_id | ForeignKey → WorkType | NOT NULL | 工種 |
| cost_category_id | ForeignKey → CostCategory | NOT NULL | 原価区分 |
| name | CharField | NOT NULL | 項目名 |
| unit | CharField | | 単位 |
| quantity | DecimalField | | 数量 |
| unit_price | DecimalField | | 単価 |
| amount | DecimalField | | 金額 |

#### E2. CostTransaction — 実績原価トランザクション

Djangoアプリ: `costs`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| work_type_id | ForeignKey → WorkType | NOT NULL | 工種 |
| cost_category_id | ForeignKey → CostCategory | NOT NULL | 原価区分 |
| amount | DecimalField | NOT NULL | 金額 |
| transaction_date | DateField | NOT NULL | 発生日 |
| source_type | CharField | NOT NULL | 発生元種別: daily_report, po_item, outsourcing, expense, reversal |
| source_id | BigIntegerField | NULL | 発生元ID |
| supplier_id | ForeignKey → Supplier | NULL | 仕入先 |
| manhours | DecimalField | NULL | 工数 |

---

### F. 材料管理

#### F1. Material — 材料マスタ

Djangoアプリ: `materials`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | コード |
| name | CharField | NOT NULL | 材料名 |
| unit | CharField | | 単位 |
| category | CharField | | 分類 |
| work_type_id | ForeignKey → WorkType | NULL | 工種 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### F2. PurchaseOrder — 発注書

Djangoアプリ: `materials`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | ForeignKey → Site | NOT NULL | 現場 |
| supplier_id | ForeignKey → Supplier | NOT NULL | 仕入先 |
| order_date | DateField | NOT NULL | 発注日 |
| status | CharField | NOT NULL | 状態: draft, ordered, partially_received, received, cancelled |

#### F3. PurchaseOrderItem — 発注明細

Djangoアプリ: `materials`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| purchase_order_id | ForeignKey → PurchaseOrder | NOT NULL | 発注書 |
| material_id | ForeignKey → Material | NOT NULL | 材料 |
| quantity | DecimalField | NOT NULL | 数量 |
| unit_price | DecimalField | NOT NULL | 単価 |
| work_type_id | ForeignKey → WorkType | NOT NULL | 工種 |

---

### G. 入札管理

#### G1. BidProject — 入札案件

Djangoアプリ: `bids`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| title | CharField | NOT NULL | 案件名 |
| client | CharField | | 発注者 |
| region | CharField | | 地域 |
| category | CharField | | 工事種別 |
| deadline | DateField | NULL | 入札期限 |
| budget | DecimalField | | 予算額 |
| source_url | URLField | | 情報源URL |
| status | CharField | NOT NULL | 状態: new, considering, bid, won, lost, skipped |

#### G2. BidCost — 入札原価

Djangoアプリ: `bids`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| project_id | OneToOneField → BidProject | NOT NULL, UNIQUE | 入札案件 |
| estimate_amount | DecimalField | | 見積額 |
| actual_cost | DecimalField | | 実際原価 |
| memo | TextField | | メモ |

#### G3. BidCompetitor — 競合情報

Djangoアプリ: `bids`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| project_id | ForeignKey → BidProject | NOT NULL | 入札案件 |
| competitor_name | CharField | NOT NULL | 競合名 |
| competitor_amount | DecimalField | | 競合金額 |
| source | CharField | | 情報源 |
| memo | TextField | | メモ |

#### G4. ScrapeTarget — スクレイピング対象

Djangoアプリ: `bids`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | 名称 |
| url | URLField | NOT NULL | URL |
| region | CharField | | 地域 |
| is_active | BooleanField | DEFAULT true | 有効 |
| last_scraped_at | DateTimeField | NULL | 最終取得日時 |

#### G5. UnitPrice — 単価マスタ

Djangoアプリ: `bids`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| category | CharField | NOT NULL | カテゴリ |
| item_name | CharField | NOT NULL | 品目名 |
| unit | CharField | | 単位 |
| unit_price | DecimalField | | 単価 |
| memo | TextField | | メモ |

#### G6. Qualification — 入札参加資格

Djangoアプリ: `bids`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| issuer | CharField | NOT NULL | 発注機関 |
| category | CharField | | 業種区分 |
| grade | CharField | | 等級 |
| keisin_score | IntegerField | NULL | 経審点 |
| total_score | IntegerField | NULL | 総合点 |
| vendor_number | CharField | | 業者番号 |
| valid_from | DateField | NULL | 有効開始日 |
| valid_until | DateField | NULL | 有効期限 |
| application_type | CharField | | 申請種別 |
| application_method | CharField | | 申請方法 |
| renewed | BooleanField | DEFAULT false | 更新済 |
| memo | TextField | | メモ |

---

### H. 人材管理

#### H1. Worker — 作業員

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | OneToOneField → User | NULL, UNIQUE | ユーザーアカウント（ログイン不要の場合NULL） |
| employee_code | CharField | NOT NULL | 社員番号 |
| name | CharField | NOT NULL | 氏名 |
| name_kana | CharField | | フリガナ |
| job_title_id | ForeignKey → JobTitle | NULL | 職種 |
| position_id | ForeignKey → Position | NULL | 役職 |
| skill_tags | JSONField | | スキルタグ |
| hourly_cost | DecimalField | | 時間単価 |
| phone | CharField | | 電話番号 |
| hire_date | DateField | NULL | 入社日 |
| is_active | BooleanField | DEFAULT true | 有効 |
| note | TextField | | 備考 |
| discord_user_id | CharField | | Discord ユーザーID |
| allowed_apps | JSONField | | 利用可能アプリ |

#### H2. JobTitle — 職種マスタ

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | 職種名 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### H3. Position — 役職マスタ

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | 役職名 |
| rank | IntegerField | NOT NULL | 序列 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### H4. WorkerQualification — 作業員資格

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| worker_id | ForeignKey → Worker | NOT NULL | 作業員 |
| name | CharField | NOT NULL | 資格名 |
| category | CharField | NOT NULL | 区分: license, skill_course, education, other |
| acquired_date | DateField | NULL | 取得日 |
| expiry_date | DateField | NULL | 有効期限 |
| certificate_image | ImageField | | 証明書画像 |
| note | TextField | | 備考 |

#### H5. HealthCheckup — 健康診断

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| worker_id | ForeignKey → Worker | NOT NULL | 作業員 |
| checkup_date | DateField | NOT NULL | 受診日 |
| result | CharField | NOT NULL | 判定: normal, observation, reexam, treatment |
| institution | CharField | | 受診機関 |
| memo | TextField | | メモ |
| report_file | FileField | | 結果ファイル |

#### H6. EvaluationTemplate — 評価テンプレート

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | テンプレート名 |
| sections | JSONField | | 評価項目 |
| survey_items | JSONField | | 質問詳細 |
| scale | JSONField | | 評価スケール |
| overall | JSONField | | 総合所見項目 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### H7. WorkerEvaluation — 作業員評価

Djangoアプリ: `workers`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| worker_id | ForeignKey → Worker | NOT NULL | 作業員 |
| evaluated_by_id | ForeignKey → User | NULL | 評価者 |
| template_id | ForeignKey → EvaluationTemplate | NULL | 使用テンプレート |
| period | CharField | NOT NULL | 評価期間 |
| score | IntegerField | NULL | 総合評点 |
| comment | TextField | | 総合コメント |
| responses | JSONField | | アンケート回答 |
| overall_responses | JSONField | | 総合所見回答 |

---

### I. 取引先・マスタ

#### I1. WorkType — 工種マスタ

Djangoアプリ: `masters`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | コード |
| name | CharField | NOT NULL | 工種名 |
| parent_id | ForeignKey → WorkType | NULL | 親工種（階層化） |
| display_order | IntegerField | DEFAULT 0 | 表示順 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### I2. CostCategory — 原価区分マスタ

Djangoアプリ: `masters`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | コード |
| name | CharField | NOT NULL | 区分名 |
| display_order | IntegerField | DEFAULT 0 | 表示順 |

> **注**: CostCategory は company_id を持たない（全テナント共通マスタ）。

#### I3. Customer — 得意先

Djangoアプリ: `masters`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | コード |
| name | CharField | NOT NULL | 得意先名 |
| address | TextField | | 住所 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### I4. Supplier — 仕入先

Djangoアプリ: `masters`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | CharField | NOT NULL | コード |
| name | CharField | NOT NULL | 仕入先名 |
| contact_info | TextField | | 連絡先 |
| is_active | BooleanField | DEFAULT true | 有効 |

#### I5. WorkStandard — 作業標準

Djangoアプリ: `masters`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| work_type_id | ForeignKey → WorkType | NOT NULL | 工種 |
| name | CharField | NOT NULL | 作業名 |
| unit | CharField | | 単位 |
| standard_unit_cost | DecimalField | | 標準単価 |
| standard_manhours | DecimalField | | 標準工数 |
| valid_from | DateField | | 有効開始日 |
| is_active | BooleanField | DEFAULT true | 有効 |

---

### J. 開発管理

#### J1. DevProject — 開発プロジェクト

Djangoアプリ: `devkanri`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | プロジェクト名 |
| description | TextField | | 説明 |
| status | CharField | NOT NULL | ステータス: planning, in_progress, completed, suspended |
| assignee_id | ForeignKey → User | NULL | 責任者 |
| start_date | DateField | NULL | 開始日 |
| due_date | DateField | NULL | 期限 |
| discord_webhook_url | URLField | | Discord Webhook URL |

#### J2. DevTask — 開発タスク

Djangoアプリ: `devkanri`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| project_id | ForeignKey → DevProject | NOT NULL | プロジェクト |
| title | CharField | NOT NULL | タイトル |
| description | TextField | | 詳細 |
| status | CharField | NOT NULL | ステータス: open, in_progress, review, done, closed |
| priority | CharField | NOT NULL | 優先度: low, medium, high, critical |
| category | CharField | NOT NULL | カテゴリ: feature, bug, refactor, docs, test, infra, other |
| assignee_id | ForeignKey → User | NULL | 担当者 |
| due_date | DateField | NULL | 期限 |
| estimate_hours | DecimalField | NULL | 見積(h) |
| actual_hours | DecimalField | NULL | 実績(h) |
| sort_order | IntegerField | DEFAULT 0 | 表示順 |

#### J3. DevComment — タスクコメント

Djangoアプリ: `devkanri`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| task_id | ForeignKey → DevTask | NOT NULL | タスク |
| author_id | ForeignKey → User | NULL | 投稿者 |
| body | TextField | NOT NULL | 本文 |

---

### K. 通知

#### K1. Notification — 通知

Djangoアプリ: `notifications`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| recipient_id | ForeignKey → User | NOT NULL | 通知先 |
| title | CharField | NOT NULL | タイトル |
| body | TextField | | 本文 |
| level | CharField | NOT NULL | 重要度: info, warning, error |
| module | CharField | NOT NULL | 発生モジュール: reports, costs, materials, bids, schedules, workers, devkanri, masters, system |
| channel | CharField | NOT NULL | 通知チャネル: in_app, email, discord |
| reference_type | CharField | | 参照先モデル |
| reference_id | PositiveBigIntegerField | NULL | 参照先ID |
| reference_url | CharField | | 参照先URL |
| is_read | BooleanField | DEFAULT false | 既読 |
| read_at | DateTimeField | NULL | 既読日時 |
| sent_at | DateTimeField | NOT NULL | 送信日時 |

#### K2. AlertRule — アラートルール

Djangoアプリ: `notifications`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | CharField | NOT NULL | ルール名 |
| alert_type | CharField | NOT NULL | アラート種別: cost_threshold, qualification_expiry, schedule_delay, bid_deadline, safety_incomplete |
| is_active | BooleanField | DEFAULT true | 有効 |
| threshold_value | IntegerField | NULL | 閾値 |
| notification_level | CharField | NOT NULL | 通知レベル: info, warning, error |
| notify_channels | JSONField | | 通知チャネル |
| notify_roles | JSONField | | 通知先ロール |

#### K3. AlertLog — アラート発火ログ

Djangoアプリ: `notifications`

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| alert_rule_id | ForeignKey → AlertRule | NOT NULL | アラートルール |
| reference_type | CharField | NOT NULL | 参照先モデル |
| reference_id | PositiveBigIntegerField | NOT NULL | 参照先ID |
| triggered_at | DateTimeField | NOT NULL | 発火日時 |
| detail | TextField | | 詳細 |

---

## インデックス設計（主要）

```sql
-- テナント分離（全テーブル共通）
-- Django ORM のクエリは常に WHERE company_id = %s を付与する

-- 日報の検索
CREATE INDEX idx_dailyreport_site_date ON reports_dailyreport(company_id, site_id, report_date);
CREATE INDEX idx_dailyreport_worker ON reports_dailyreport(company_id, worker_id, report_date);

-- 安全書類の未記入チェック
CREATE INDEX idx_safetyrecord_date ON reports_safetyrecord(company_id, record_date, completed);

-- 原価集計
CREATE INDEX idx_costtransaction_site ON costs_costtransaction(company_id, site_id, transaction_date);
CREATE INDEX idx_budgetitem_site ON costs_budgetitem(company_id, site_id);

-- 入札期限
CREATE INDEX idx_bidproject_deadline ON bids_bidproject(company_id, deadline)
  WHERE status IN ('new', 'considering');

-- 資格期限
CREATE INDEX idx_workerqualification_expiry ON workers_workerqualification(company_id, expiry_date)
  WHERE expiry_date IS NOT NULL;

-- 配置管理
CREATE INDEX idx_assignment_worker ON schedules_assignment(company_id, worker_id, start_date);
CREATE INDEX idx_assignment_site ON schedules_assignment(company_id, site_id, start_date);

-- 通知
CREATE INDEX idx_notification_recipient ON notifications_notification(company_id, recipient_id, is_read, sent_at DESC);

-- 材料
CREATE INDEX idx_material_worktype ON materials_material(company_id, work_type_id);
```

---

## HistoricalRecords（監査ログ）

django-simple-history を使用し、主要テーブルに対してシャドーテーブル（`historical_*`）が自動生成される。

シャドーテーブルには元テーブルの全カラムに加え以下が追加される:

| カラム | 型 | 説明 |
|--------|-----|------|
| history_id | AutoField | 履歴レコードID |
| history_date | DateTimeField | 変更日時 |
| history_change_reason | CharField | 変更理由 |
| history_type | CharField | '+' (作成), '~' (更新), '-' (削除) |
| history_user_id | ForeignKey → User | 変更操作者 |

---

## テーブル数サマリ

| 領域 | テーブル数 | テーブル名 |
|------|-----------|-----------|
| テナント | 2 | Company, CompanyApp |
| ユーザー・権限 | 5 | User, Department, Role, ModulePermission, UserRole |
| 現場・工期 | 5 | Site, Process, Phase, Milestone, Assignment |
| 日報 | 4 | DailyReport, DailyReportMaterial, SafetyTemplate, SafetyRecord |
| 原価 | 2 | BudgetItem, CostTransaction |
| 材料 | 3 | Material, PurchaseOrder, PurchaseOrderItem |
| 入札 | 6 | BidProject, BidCost, BidCompetitor, ScrapeTarget, UnitPrice, Qualification |
| 人材 | 7 | Worker, JobTitle, Position, WorkerQualification, HealthCheckup, EvaluationTemplate, WorkerEvaluation |
| 取引先・マスタ | 5 | WorkType, CostCategory, Customer, Supplier, WorkStandard |
| 開発 | 3 | DevProject, DevTask, DevComment |
| 通知 | 3 | Notification, AlertRule, AlertLog |
| **合計** | **45** | — |

> **注**: 上記に加え、django-simple-history による `historical_*` シャドーテーブルが対象モデル数分生成される。Django 標準の `auth_*`, `django_*`, `admin_*` テーブルも別途存在する。

---

*次フェーズ: 技術選定 → 画面設計*
