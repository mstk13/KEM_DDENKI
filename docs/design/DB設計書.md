# 電機屋 業務管理アプリ — DB設計書

**作成日**: 2026-08-03
**前提**: PostgreSQL（リレーショナルDB）を想定。ファイルストレージはオブジェクトストレージ（S3互換）を併用。

---

## ER図（概要）

```
┌──────────┐    ┌──────────┐    ┌──────────────┐
│  users   │───<│user_roles│>───│    roles     │
└────┬─────┘    └──────────┘    └──────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                      日報系                                │
     │  │  ┌────────────┐   ┌──────────────────┐                    │
     ├──┼─<│daily_reports│──<│daily_report_items │                   │
     │  │  └─────┬──────┘   └────────┬─────────┘                    │
     │  │        │                   │                               │
     │  │        │           ┌───────┴──────────┐                    │
     │  │        │           │report_material_use│                   │
     │  │        │           └──────────────────┘                    │
     │  │        │                                                   │
     │  │  ┌─────┴──────────────┐                                    │
     │  │  │daily_report_safety │  KY等の記入チェック                  │
     │  │  └────────────────────┘                                    │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    現場・工期系                              │
     │  │  ┌──────┐   ┌────────────┐   ┌────────────┐               │
     │  ├─<│sites │──<│ phases     │──<│milestones  │               │
     │  │  └──┬───┘   └────────────┘   └────────────┘               │
     │  │     │                                                      │
     │  │     │   ┌───────────────────┐                              │
     │  │     └──<│site_assignments   │  配置管理                     │
     │  │         └───────────────────┘                              │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    原価系                                   │
     │  │  ┌──────────┐   ┌──────────────┐                           │
     │  │  │ budgets  │   │ actual_costs │                           │
     │  │  └──────────┘   └──────────────┘                           │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    材料系                                   │
     │  │  ┌──────────────┐  ┌────────────┐  ┌─────────────────┐    │
     │  │  │material_items│  │ quotations │─<│quotation_items  │    │
     │  │  └──────────────┘  └────────────┘  └─────────────────┘    │
     │  │                    ┌──────────────┐  ┌─────────────────┐   │
     │  │                    │purchase_orders│─<│po_items         │  │
     │  │                    └──────────────┘  └─────────────────┘   │
     │  │                    ┌──────────┐  ┌───────────────┐         │
     │  │                    │deliveries│─<│delivery_items │         │
     │  │                    └──────────┘  └───────────────┘         │
     │  │                    ┌──────────┐                            │
     │  │                    │inventory │                            │
     │  │                    └──────────┘                            │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    入札系                                   │
     │  │  ┌─────────────┐  ┌──────────────┐                        │
     │  │  │bid_projects │─<│bid_documents │                        │
     │  │  └──────┬──────┘  └──────────────┘                        │
     │  │         └──<┌──────────────┐                               │
     │  │             │bid_competitors│                              │
     │  │             └──────────────┘                               │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    人材系                                   │
     │  │  ┌───────────────┐  ┌────────────┐  ┌───────────────┐     │
     │  │  │qualifications │  │ trainings  │  │health_checks  │     │
     │  │  └───────────────┘  └────────────┘  └───────────────┘     │
     │  │  ┌───────────┐                                             │
     │  │  │skill_maps │                                             │
     │  │  └───────────┘                                             │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    取引先系                                  │
     │  │  ┌──────────┐  ┌───────────────────┐  ┌──────────────┐    │
     │  │  │ partners │─<│partner_evaluations│  │business_cards│    │
     │  │  └──────────┘  └───────────────────┘  └──────────────┘    │
     │  └───────────────────────────────────────────────────────────┘
     │
     │  ┌───────────────────────────────────────────────────────────┐
     │  │                    共通系                                   │
     │  │  ┌──────────────┐  ┌──────────┐  ┌──────────┐             │
     │  │  │notifications │  │ files    │  │dev_tasks │             │
     │  │  └──────────────┘  └──────────┘  └──────────┘             │
     │  └───────────────────────────────────────────────────────────┘
```

---

## テーブル定義

### 共通カラム規約
全テーブルに以下を含む（以降の定義では省略）:
- `id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
- `updated_at` TIMESTAMPTZ NOT NULL DEFAULT now()

---

### A. ユーザー・権限

#### A1. users — ユーザー
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| email | VARCHAR(255) | UNIQUE NOT NULL | ログインメール |
| password_hash | VARCHAR(255) | NOT NULL | ハッシュ化パスワード |
| name | VARCHAR(100) | NOT NULL | 氏名 |
| phone | VARCHAR(20) | | 電話番号 |
| company_type | VARCHAR(20) | NOT NULL | 'internal' / 'partner' |
| partner_id | UUID | FK → partners | 協力会社の場合 |
| is_active | BOOLEAN | DEFAULT true | 有効/無効 |
| discord_id | VARCHAR(50) | | Discord連携用 |

#### A2. roles — ロール定義
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(50) | UNIQUE NOT NULL | 'president','executive','site_manager','office_staff','partner_worker','developer' |
| description | TEXT | | ロール説明 |

#### A3. user_roles — ユーザー×ロール
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users | — |
| role_id | UUID | FK → roles | — |
| granted_by | UUID | FK → users | 権限付与者（社長等） |

**UNIQUE(user_id, role_id)**

#### A4. module_permissions — モジュール別権限
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| role_id | UUID | FK → roles | — |
| module | VARCHAR(50) | NOT NULL | 'reports','costs','bids' 等 |
| can_read | BOOLEAN | DEFAULT false | 閲覧 |
| can_write | BOOLEAN | DEFAULT false | 編集 |
| can_admin | BOOLEAN | DEFAULT false | 管理 |

**UNIQUE(role_id, module)**

---

### B. 現場・工期

#### B1. sites — 現場
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(200) | NOT NULL | 現場名 |
| address | TEXT | | 住所 |
| client_id | UUID | FK → partners | 発注者 |
| status | VARCHAR(20) | NOT NULL DEFAULT 'active' | 'planning','active','completed','suspended' |
| planned_start | DATE | | 予定開始日 |
| planned_end | DATE | | 予定終了日 |
| actual_start | DATE | | 実際開始日 |
| actual_end | DATE | | 実際終了日 |
| target_profit_rate | DECIMAL(5,2) | | 目標粗利率(%) |
| bid_project_id | UUID | FK → bid_projects | 入札案件から連携 |
| notes | TEXT | | 備考 |

#### B2. work_types — 工種マスタ
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(100) | UNIQUE NOT NULL | 工種名 |
| description | TEXT | | 説明 |
| sort_order | INT | DEFAULT 0 | 表示順 |

#### B3. phases — 工程（ガントチャート用）
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| name | VARCHAR(200) | NOT NULL | 工程名 |
| planned_start | DATE | NOT NULL | 予定開始日 |
| planned_end | DATE | NOT NULL | 予定終了日 |
| actual_start | DATE | | 実績開始日 |
| actual_end | DATE | | 実績終了日 |
| progress | INT | DEFAULT 0 | 進捗率(%) |
| parent_phase_id | UUID | FK → phases | 親工程（階層化） |
| sort_order | INT | DEFAULT 0 | 表示順 |
| is_partner | BOOLEAN | DEFAULT false | 協力会社工程か |

#### B4. milestones — マイルストーン
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| name | VARCHAR(200) | NOT NULL | 検査日、引渡日、申請期限等 |
| due_date | DATE | NOT NULL | 期限 |
| completed | BOOLEAN | DEFAULT false | 完了フラグ |
| milestone_type | VARCHAR(50) | | 'inspection','handover','deadline' 等 |

#### B5. site_assignments — 配置管理
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| user_id | UUID | FK → users, NOT NULL | 作業員 |
| assigned_date | DATE | NOT NULL | 配置日 |
| role_on_site | VARCHAR(50) | | '職長','作業員' 等 |

**UNIQUE(site_id, user_id, assigned_date)**

#### B6. phase_templates — 工程テンプレート
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(200) | NOT NULL | テンプレート名 |
| description | TEXT | | 説明 |

#### B7. phase_template_items — テンプレート明細
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| template_id | UUID | FK → phase_templates, NOT NULL | — |
| name | VARCHAR(200) | NOT NULL | 工程名 |
| offset_days_start | INT | NOT NULL | 開始日オフセット |
| offset_days_end | INT | NOT NULL | 終了日オフセット |
| parent_item_id | UUID | FK → phase_template_items | 親工程 |
| sort_order | INT | DEFAULT 0 | 表示順 |

---

### C. 日報

#### C1. daily_reports — 日報ヘッダー
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| report_date | DATE | NOT NULL | 作業日 |
| weather | VARCHAR(20) | | '晴','曇','雨','雪' 等 |
| reported_by | UUID | FK → users, NOT NULL | 入力者 |
| approved | BOOLEAN | DEFAULT false | 承認フラグ（任意） |
| approved_by | UUID | FK → users | 承認者 |
| approved_at | TIMESTAMPTZ | | 承認日時 |
| notes | TEXT | | その他（メモ） |

**UNIQUE(site_id, report_date)**

#### C2. daily_report_items — 日報明細（作業員別）
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| report_id | UUID | FK → daily_reports, NOT NULL | 日報 |
| worker_id | UUID | FK → users, NOT NULL | 作業員 |
| work_type_id | UUID | FK → work_types | 工種 |
| work_description | TEXT | | 作業内容 |
| start_time | TIME | NOT NULL | 開始時間 |
| end_time | TIME | NOT NULL | 終了時間 |
| regular_hours | DECIMAL(4,2) | | 通常時間（自動計算） |
| overtime_hours | DECIMAL(4,2) | | 残業時間（自動計算） |
| is_partner_worker | BOOLEAN | DEFAULT false | 協力会社の作業員か |
| partner_id | UUID | FK → partners | 協力会社 |

#### C3. report_material_usage — 日報の使用材料
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| report_id | UUID | FK → daily_reports, NOT NULL | 日報 |
| material_id | UUID | FK → material_items | 材料マスタ |
| material_name | VARCHAR(200) | | マスタ外の場合の自由入力 |
| quantity | DECIMAL(10,2) | | 使用量 |
| unit | VARCHAR(20) | | 単位 |

#### C4. safety_templates — 安全書類ひな型
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| name | VARCHAR(200) | NOT NULL | 'KY活動記録','TBM記録' 等 |
| template_file_id | UUID | FK → files | ひな型ファイル |
| is_daily_required | BOOLEAN | DEFAULT true | 毎日必須か |

#### C5. safety_records — 安全書類の記入チェック
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| template_id | UUID | FK → safety_templates, NOT NULL | ひな型 |
| worker_id | UUID | FK → users, NOT NULL | 作業員 |
| record_date | DATE | NOT NULL | 記入日 |
| completed | BOOLEAN | DEFAULT false | 記入済みか |
| alerted | BOOLEAN | DEFAULT false | アラート送信済みか |

**UNIQUE(template_id, worker_id, record_date)**

---

### D. 原価管理

#### D1. budgets — 予算
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| work_type_id | UUID | FK → work_types | 工種（NULLなら現場全体） |
| cost_category | VARCHAR(20) | NOT NULL | 'material','labor','outsource','expense' |
| amount | DECIMAL(14,2) | NOT NULL | 予算額 |

**UNIQUE(site_id, work_type_id, cost_category)**

#### D2. actual_costs — 実績原価
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| cost_category | VARCHAR(20) | NOT NULL | 同上 |
| work_type_id | UUID | FK → work_types | 工種 |
| cost_date | DATE | NOT NULL | 発生日 |
| amount | DECIMAL(14,2) | NOT NULL | 金額 |
| description | TEXT | | 内容 |
| source_type | VARCHAR(20) | | 'daily_report','purchase_order','manual' |
| source_id | UUID | | 元データのID |

#### D3. cost_alerts — 原価アラート履歴
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites, NOT NULL | 現場 |
| cost_category | VARCHAR(20) | NOT NULL | — |
| threshold_pct | INT | NOT NULL | 75, 80, 90, 100 |
| triggered_at | TIMESTAMPTZ | NOT NULL | 発火日時 |
| notified_users | UUID[] | | 通知先ユーザー |

---

### E. 材料管理

#### E1. material_items — 材料マスタ
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(200) | NOT NULL | 材料名 |
| category | VARCHAR(100) | | カテゴリ |
| unit | VARCHAR(20) | | 標準単位 |
| standard_price | DECIMAL(12,2) | | 参考単価 |
| description | TEXT | | 説明 |

#### E2. quotations — 見積
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites | 現場 |
| supplier_id | UUID | FK → partners, NOT NULL | 仕入先 |
| quotation_date | DATE | NOT NULL | 見積日 |
| valid_until | DATE | | 有効期限 |
| total_amount | DECIMAL(14,2) | | 合計金額 |
| status | VARCHAR(20) | DEFAULT 'draft' | 'draft','received','accepted','rejected' |
| file_id | UUID | FK → files | 添付ファイル（PDF/Excel） |
| notes | TEXT | | 備考 |

#### E3. quotation_items — 見積明細
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| quotation_id | UUID | FK → quotations, NOT NULL | — |
| material_id | UUID | FK → material_items | 材料 |
| material_name | VARCHAR(200) | | マスタ外の場合 |
| quantity | DECIMAL(10,2) | NOT NULL | 数量 |
| unit_price | DECIMAL(12,2) | NOT NULL | 単価 |
| amount | DECIMAL(14,2) | NOT NULL | 金額 |

#### E4. purchase_orders — 発注
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| site_id | UUID | FK → sites | 現場 |
| supplier_id | UUID | FK → partners, NOT NULL | 仕入先 |
| quotation_id | UUID | FK → quotations | 元見積 |
| order_date | DATE | NOT NULL | 発注日 |
| total_amount | DECIMAL(14,2) | | 合計金額 |
| status | VARCHAR(20) | DEFAULT 'ordered' | 'ordered','partially_delivered','delivered','inspected' |
| file_id | UUID | FK → files | 発注書ファイル |

#### E5. po_items — 発注明細
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| po_id | UUID | FK → purchase_orders, NOT NULL | — |
| material_id | UUID | FK → material_items | 材料 |
| material_name | VARCHAR(200) | | — |
| quantity | DECIMAL(10,2) | NOT NULL | 発注数量 |
| unit_price | DECIMAL(12,2) | NOT NULL | 単価 |
| amount | DECIMAL(14,2) | NOT NULL | 金額 |

#### E6. deliveries — 納品
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| po_id | UUID | FK → purchase_orders, NOT NULL | 発注 |
| delivery_date | DATE | NOT NULL | 納品日 |
| inspected | BOOLEAN | DEFAULT false | 検収済み |
| inspected_by | UUID | FK → users | 検収者 |
| inspected_at | TIMESTAMPTZ | | 検収日時 |
| notes | TEXT | | 備考 |

#### E7. delivery_items — 納品明細
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| delivery_id | UUID | FK → deliveries, NOT NULL | — |
| material_id | UUID | FK → material_items | 材料 |
| ordered_qty | DECIMAL(10,2) | | 発注数量 |
| delivered_qty | DECIMAL(10,2) | NOT NULL | 納品数量 |
| is_ok | BOOLEAN | DEFAULT true | 数量OK |

#### E8. inventory — 在庫
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| material_id | UUID | FK → material_items, NOT NULL | 材料 |
| site_id | UUID | FK → sites | 現場（NULL=本社倉庫） |
| quantity | DECIMAL(10,2) | NOT NULL DEFAULT 0 | 在庫数 |
| last_updated | TIMESTAMPTZ | DEFAULT now() | 最終更新 |

**UNIQUE(material_id, site_id)**

---

### F. 入札管理

#### F1. bid_projects — 入札案件
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(300) | NOT NULL | 案件名 |
| client_name | VARCHAR(200) | | 発注者名 |
| client_id | UUID | FK → partners | 取引先 |
| region | VARCHAR(100) | | 地域 |
| category | VARCHAR(100) | | カテゴリ |
| source | VARCHAR(20) | NOT NULL | 'manual','scraping','email' |
| bid_deadline | TIMESTAMPTZ | | 入札期限 |
| estimated_amount | DECIMAL(14,2) | | 見積金額 |
| ai_estimated_amount | DECIMAL(14,2) | | AI見積金額 |
| our_bid_amount | DECIMAL(14,2) | | 自社入札額 |
| status | VARCHAR(20) | DEFAULT 'new' | 'new','preparing','submitted','won','lost','cancelled' |
| result_notified_at | TIMESTAMPTZ | | 結果通知日 |
| notes | TEXT | | 備考 |

#### F2. bid_documents — 入札書類
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| bid_project_id | UUID | FK → bid_projects, NOT NULL | 案件 |
| name | VARCHAR(200) | NOT NULL | 書類名 |
| file_id | UUID | FK → files, NOT NULL | ファイル |
| doc_type | VARCHAR(50) | | '仕様書','図面','見積書' 等 |

#### F3. bid_competitors — 競合情報
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| bid_project_id | UUID | FK → bid_projects, NOT NULL | 案件 |
| competitor_name | VARCHAR(200) | NOT NULL | 競合社名 |
| bid_amount | DECIMAL(14,2) | | 競合入札額 |
| analysis | TEXT | | 強み弱み分析（Phase 2） |

---

### G. 人材管理

#### G1. qualifications — 資格
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users, NOT NULL | 作業員 |
| name | VARCHAR(200) | NOT NULL | 資格名 |
| acquired_date | DATE | | 取得日 |
| expiry_date | DATE | | 有効期限 |
| is_active | BOOLEAN | DEFAULT true | 有効（期限切れ更新なしでfalse） |
| certificate_file_id | UUID | FK → files | 証明書ファイル |

#### G2. qualification_alerts — 資格アラート履歴
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| qualification_id | UUID | FK → qualifications, NOT NULL | 資格 |
| alert_type | VARCHAR(20) | NOT NULL | '1year','6month','3month','1month','1week','expired' |
| sent_at | TIMESTAMPTZ | NOT NULL | 送信日時 |

#### G3. trainings — 研修記録
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users, NOT NULL | 受講者 |
| name | VARCHAR(200) | NOT NULL | 研修名 |
| training_date | DATE | NOT NULL | 受講日 |
| provider | VARCHAR(200) | | 実施機関 |
| certificate_file_id | UUID | FK → files | 修了証ファイル |
| notes | TEXT | | 備考 |

#### G4. health_checks — 健康診断
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users, NOT NULL | 対象者 |
| check_date | DATE | NOT NULL | 受診日 |
| result_summary | TEXT | | 結果概要 |
| result_file_id | UUID | FK → files | 結果PDF |
| next_check_date | DATE | | 次回予定日 |

#### G5. skill_maps — スキルマップ
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users, NOT NULL | 作業員 |
| skill_name | VARCHAR(200) | NOT NULL | スキル名 |
| level | INT | DEFAULT 1 | 1〜5のレベル |
| notes | TEXT | | 補足 |

**UNIQUE(user_id, skill_name)**

#### G6. attendance_summary — 勤怠集計（日報から自動生成）
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users, NOT NULL | 作業員 |
| year_month | VARCHAR(7) | NOT NULL | '2026-08' |
| work_days | INT | DEFAULT 0 | 出勤日数 |
| total_regular_hours | DECIMAL(6,2) | DEFAULT 0 | 通常時間合計 |
| total_overtime_hours | DECIMAL(6,2) | DEFAULT 0 | 残業時間合計 |
| paid_leave_used | INT | DEFAULT 0 | 有休消化日数 |

**UNIQUE(user_id, year_month)**

---

### H. 取引先管理

#### H1. partners — 取引先
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| name | VARCHAR(200) | NOT NULL | 会社名 |
| partner_type | VARCHAR(20) | NOT NULL | 'client','supplier','subcontractor','other' |
| industry | VARCHAR(100) | | 業種 |
| region | VARCHAR(100) | | 地域 |
| scale | VARCHAR(50) | | 取引規模 |
| address | TEXT | | 住所 |
| phone | VARCHAR(20) | | 電話番号 |
| email | VARCHAR(255) | | メールアドレス |
| notes | TEXT | | 備考 |

#### H2. partner_contacts — 取引先担当者
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| partner_id | UUID | FK → partners, NOT NULL | 取引先 |
| name | VARCHAR(100) | NOT NULL | 担当者名 |
| position | VARCHAR(100) | | 役職 |
| phone | VARCHAR(20) | | 電話番号 |
| email | VARCHAR(255) | | メール |

#### H3. partner_evaluations — 発注先評価
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| partner_id | UUID | FK → partners, NOT NULL | 取引先 |
| evaluator_id | UUID | FK → users, NOT NULL | 評価者 |
| evaluation_date | DATE | NOT NULL | 評価日 |
| price_rating | INT | CHECK 1-5 | 金額評価 |
| delivery_rating | INT | CHECK 1-5 | 納期評価 |
| quality_rating | INT | CHECK 1-5 | 品質評価 |
| service_description | TEXT | | サービス/商品内容 |
| notes | TEXT | | 備考 |

#### H4. business_cards — 名刺
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| partner_id | UUID | FK → partners | 取引先 |
| contact_id | UUID | FK → partner_contacts | 担当者 |
| image_file_id | UUID | FK → files, NOT NULL | 名刺画像 |

---

### I. 開発管理

#### I1. dev_tasks — 開発タスク
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| title | VARCHAR(300) | NOT NULL | タスク名 |
| description | TEXT | | 説明 |
| assignee_id | UUID | FK → users | 担当者 |
| status | VARCHAR(20) | DEFAULT 'todo' | 'todo','in_progress','review','done' |
| priority | VARCHAR(10) | DEFAULT 'medium' | 'low','medium','high','urgent' |
| due_date | DATE | | 期限 |
| github_issue_url | VARCHAR(500) | | GitHub issue URL |
| github_pr_url | VARCHAR(500) | | GitHub PR URL |

#### I2. dev_task_comments — タスクコメント
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| task_id | UUID | FK → dev_tasks, NOT NULL | タスク |
| user_id | UUID | FK → users, NOT NULL | 投稿者 |
| body | TEXT | NOT NULL | コメント内容 |
| source | VARCHAR(20) | DEFAULT 'app' | 'app','discord','github' |

---

### J. 共通

#### J1. files — ファイル管理
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| original_name | VARCHAR(500) | NOT NULL | 元ファイル名 |
| storage_path | VARCHAR(500) | NOT NULL | ストレージパス |
| mime_type | VARCHAR(100) | | MIME |
| file_size | BIGINT | | バイト数 |
| uploaded_by | UUID | FK → users | アップロード者 |

#### J2. notifications — 通知
| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| user_id | UUID | FK → users, NOT NULL | 通知先 |
| title | VARCHAR(300) | NOT NULL | タイトル |
| body | TEXT | | 本文 |
| notification_type | VARCHAR(30) | NOT NULL | 'in_app','email','discord' |
| module | VARCHAR(50) | | 発生モジュール |
| reference_type | VARCHAR(50) | | 参照先テーブル名 |
| reference_id | UUID | | 参照先ID |
| is_read | BOOLEAN | DEFAULT false | 既読 |
| sent_at | TIMESTAMPTZ | DEFAULT now() | 送信日時 |

---

## インデックス設計（主要）

```sql
-- 日報の検索
CREATE INDEX idx_daily_reports_site_date ON daily_reports(site_id, report_date);
CREATE INDEX idx_daily_report_items_worker ON daily_report_items(worker_id, report_id);

-- 安全書類の未記入チェック
CREATE INDEX idx_safety_records_date ON safety_records(record_date, completed);

-- 原価集計
CREATE INDEX idx_actual_costs_site_cat ON actual_costs(site_id, cost_category, cost_date);
CREATE INDEX idx_budgets_site ON budgets(site_id);

-- 入札期限
CREATE INDEX idx_bid_projects_deadline ON bid_projects(bid_deadline) WHERE status IN ('new','preparing');

-- 資格期限
CREATE INDEX idx_qualifications_expiry ON qualifications(expiry_date) WHERE is_active = true;

-- 配置管理
CREATE INDEX idx_site_assignments_date ON site_assignments(assigned_date, user_id);
CREATE INDEX idx_site_assignments_user ON site_assignments(user_id, assigned_date);

-- 通知
CREATE INDEX idx_notifications_user ON notifications(user_id, is_read, sent_at DESC);

-- 在庫
CREATE INDEX idx_inventory_material ON inventory(material_id, site_id);
```

---

## テーブル数サマリ

| 領域 | テーブル数 | テーブル名 |
|------|-----------|-----------|
| ユーザー・権限 | 4 | users, roles, user_roles, module_permissions |
| 現場・工期 | 7 | sites, work_types, phases, milestones, site_assignments, phase_templates, phase_template_items |
| 日報 | 5 | daily_reports, daily_report_items, report_material_usage, safety_templates, safety_records |
| 原価 | 3 | budgets, actual_costs, cost_alerts |
| 材料 | 8 | material_items, quotations, quotation_items, purchase_orders, po_items, deliveries, delivery_items, inventory |
| 入札 | 3 | bid_projects, bid_documents, bid_competitors |
| 人材 | 6 | qualifications, qualification_alerts, trainings, health_checks, skill_maps, attendance_summary |
| 取引先 | 4 | partners, partner_contacts, partner_evaluations, business_cards |
| 開発 | 2 | dev_tasks, dev_task_comments |
| 共通 | 2 | files, notifications |
| **合計** | **44** | — |

---

*次フェーズ: 技術選定 → 画面設計*
