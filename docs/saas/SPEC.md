# 建設業向けマルチテナント業務SaaS システム基本仕様書 v0.2

対象業種: 設備工事業（初期）→ 内装工事業・解体工事業（拡張予定）
版数: v0.2 ｜ 作成日: 2026年7月31日 ｜ 前版: v0.1（2026年7月29日）

本書は v0.1 の全体構想に、技術スタック・マルチテナント方式・データ粒度の決定事項を統合し、実装に着手できる粒度まで詳細化したもの。本書と `CLAUDE.md`（第10章）を Claude Code への入力とする。

---

## 1. 目的と全体方針

企業（テナント）ごとにアプリケーションの組み合わせをパッケージ販売するマルチテナント型SaaSを構築する。設計方針は以下の5点。

1. 業種を横断して再利用できる共通コアデータモデルを最初から定義し、業種固有項目はマスタと拡張テーブルで吸収する。**業種名（設備・電気・内装・解体）をコード・クラス名・分岐条件に一切登場させない。**
2. 業務アプリケーションを疎結合な Django アプリとして構築し、テナントごとに有効化フラグで提供機能を制御する（機能制御と課金判定の単一情報源）。
3. 日報データを起点に、人材・工程・材料の実績を統一フォーマットの原価トランザクション（cost_transactions）へ正規化する。
4. 予算と実績は必ず**工種 × 原価区分**の同一粒度で記録する。この粒度が揃わないと予実対比・AI分析が成立しないため、全アプリ共通の絶対条件とする。
5. 10年以上の稼働を前提に、LTSのみの採用・依存最小・テスト/CI必須の開発規律を敷く。

## 2. 技術スタック（決定）

| 項目 | 採用 | 理由 |
|---|---|---|
| 言語 | Python 3.12 | チーム3名の習熟度。10年保守の人材確保 |
| フレームワーク | Django 5.2 LTS | 認証・権限・admin・マイグレーション標準装備。LTSサポート2028-04-30。以後もLTSのみを渡り歩く（ADR-0001） |
| DB | PostgreSQL 16 | JSONB・行レベル分離・マネージド移行の容易さ |
| パッケージ管理 | uv + lockfile | 環境差異によるデプロイ事故の排除 |
| 監査ログ | django-simple-history | 全変更履歴（誰が・いつ・前後値）。自作禁止 |
| テスト | pytest + pytest-django | |
| 静的解析 | ruff + mypy (django-stubs) | 新規コードはstrict |
| CI | GitHub Actions | PR必須、main直接コミット禁止、マイグレーション漏れ検出を含む |

外部依存の追加は「10年後もメンテナが存在するか」を基準に、ADRを書いた上でのみ許可する。

## 3. マルチテナント方式（v0.1未決事項の決定）

**共有DB・共有スキーマ + company_id による行レベル分離を採用する。**

| 方式 | 評価 |
|---|---|
| 行レベル分離（採用） | 運用・マイグレーションが1系統。Django と自然に統合。3名体制で現実的 |
| スキーマ分離 | テナント数×マイグレーション運用が発生。3名では破綻リスク |
| DB分離 | 大口顧客の個別要件時のみ将来検討 |

採用に伴う実装要件（セキュリティ上の最重要事項）:

1. テナント帰属を持つ全テーブルは `company` への外部キーを必須とする（共通基底 `TenantModel` で強制）。
2. クエリは必ず現在テナントでフィルタする。`CompanyScopedManager` をデフォルトマネージャとし、リクエストから解決したテナントを thread-local / contextvar 経由で適用する。素の `objects.all()` に相当する無フィルタアクセスは `unscoped` マネージャに隔離し、利用箇所をコードレビュー必須とする。
3. **テナント越境テストをCIに常設する。** 「A社ユーザーがB社データに到達できないこと」を、モデル・ビュー・admin の各層で検証するテストを、アプリ追加のたびに必ず追加する。
4. 全テーブルに company_id があるため、特定テナントのデータ抽出（退会時の返却・DB分離への昇格）が dump 一発で可能な状態を保つ。

## 4. アプリケーションモジュールと Django アプリ対応

| No. | アプリ名 | app_code | Djangoアプリ | 概要 |
|---|---|---|---|---|
| - | 共通基盤 | (常時有効) | core, tenants, accounts, masters | テナント・認証・マスタ。課金対象外 |
| 1 | 人材管理 | jinzai | workers | 作業員・資格・スキルタグ・時間単価 |
| 2 | 人材評価 | hyoka | evaluations | 日報実績と連動した評価 |
| 3 | 工期・工程管理 | koutei | schedule | 現場ごとの計画工程と実績 |
| 4 | 材料管理（受発注） | zairyo | materials | 資材マスタ・発注先・受発注 |
| 5 | 日報管理 | nippou | reports | 稼働・使用材料の日次記録。全実績のハブ |
| 6 | 原価・予実管理 | genka | costs | 実行予算・cost_transactions・予実対比 |
| 7〜12 | （拡張枠） | 未定 | - | 内装・解体拡張時に追加。共通コア維持 |

- `company_apps.is_enabled` が機能アクセス制御と課金判定の単一情報源（v0.1踏襲）。
- ミドルウェア/デコレータ `@app_required("nippou")` で、無効アプリのURLを 404 とする。
- No.6（原価・予実）は v0.1 の「将来拡張」から**初期リリースへ昇格**する。cost_transactions を後付けすると全テナントのデータ移行が発生するため（v0.1 §5.6 の推奨に従う）。

## 5. データモデル

記法: 全テーブルは `id (BigAuto)`, `created_at`, `updated_at`, `created_by` を持つ（core.TimeStampedModel）。テナント帰属テーブルは `company_id` 必須（core.TenantModel）。`[H]` は simple-history による履歴対象。

### 5.1 tenants / accounts（共通基盤）

```
Company        (name, industry_type*, contract_plan, is_active)        [H]
                 * 参考情報。ロジックの分岐には使用禁止（ADR-0003）
CompanyApp     (company, app_code, is_enabled, enabled_at)             [H]
User           (AbstractUser + company FK, employee_no, department FK)
                 role は独自カラムを廃止し Django Group で表現
                 （admin / manager / worker を初期Groupとして投入）
Department     (company, name, is_active)                              [H]
```

**注意: User は初回 migrate 前に必ずカスタムモデルとして定義する（ADR-0002）。**

### 5.2 masters（業種拡張の吸収層）

```
WorkType       (company, code, name, parent FK(self), display_order, is_active) [H]
                 階層例: 設備工事 > 電気 > 幹線・動力 / 弱電
                        内装工事 > 内装仕上 > 軽鉄・ボード
                 v0.1 の industry_subtype 文字列はこの階層マスタに昇格。
                 業種拡張＝マスタへの行追加のみ。コード変更ゼロ。
CostCategory   (code, name, display_order)   ※全テナント共通・システム定義
                 材料費 / 労務費 / 外注費 / 経費 の建設業4区分
Customer       (company, code, name, address, is_active)               [H]
Supplier       (company, code, name, contact_info, is_active)          [H]
WorkStandard   (company, work_type, name, unit, standard_unit_cost,
                standard_manhours, valid_from, is_active)              [H]
                 歩掛マスタ。日報実績から将来自動更新（AI段階3の入口）
```

### 5.3 sites / schedule（現場＝全業務データの起点）

```
Site           (company, code, name, customer FK, work_types M2M,
                address, status, contract_amount,
                start_date, end_date, manager FK(User))               [H]
                 status: estimating / ordered / in_progress /
                         completed / billed / cancelled
                 v0.1 の sites と skeleton の Project を一本化。
                 中小の実態に合わせ 案件=現場 を 1:1 とする。
Process        (site, work_type FK, name, planned_start, planned_end,
                actual_start, actual_end, status, display_order)      [H]
```

### 5.4 workers / evaluations

```
JobTitle       (company, name, is_active)                              [H]
                 テナントごとに定義する職種区分。
                 例: 電工 / 配管工 / CADオペ / 事務
                 hourly_cost の既定値を持たせることも将来検討。
Position       (company, name, rank, is_active)                        [H]
                 テナントごとに定義する役職。rank は序列（昇順）。
                 例: 職長(1) / 主任(2) / シニア(3) / ミドル(4) / ジュニア(5)
                 評価項目の出し分け等に利用する。
Worker         (company, user FK nullable, name, job_title FK(JobTitle),
                position FK(Position) nullable, skill_tags JSONB,
                hourly_cost, hire_date, is_active)                     [H]
                 hourly_cost は労務費原価の算出単価。履歴必須
WorkerEvaluation (company, worker, evaluated_by FK(User), period,
                  score, comment)                                      [H]
```

### 5.5 reports（日報＝実績のハブ。UX最優先）

```
DailyReport    (company, site, worker, report_date, process FK nullable,
                work_type FK, work_hours, memo, status)                [H]
                 status: draft / submitted / approved
                 UNIQUE(site, worker, report_date, work_type)
DailyReportMaterial (daily_report, material FK, quantity_used)         [H]
```

日報UX要件（v0.1 §3 の最優先方針を具体化）:
- スマホ縦画面で3タップ以内に前日コピー入力が完了すること
- 現場・工程・工種は当人の直近入力から候補提示
- オフライン一時保存（送信失敗時のローカル保持）は v1.1 で検討
- 承認フロー: worker が submit → manager が approve。approved 後の編集は履歴に残る訂正のみ

### 5.6 materials（受発注）

```
Material           (company, code, name, unit, category,
                    work_type FK nullable, is_active)                  [H]
PurchaseOrder      (company, site, supplier, order_date, status)       [H]
                     status: draft / ordered / partially_received /
                             received / cancelled
PurchaseOrderItem  (purchase_order, material, quantity, unit_price,
                    work_type FK)                                      [H]
                     work_type を明細に持つ＝原価粒度を発注時点で確定
```

### 5.7 costs（予実管理と統一原価データ）

```
BudgetItem       (company, site, work_type, cost_category, name,
                  unit, quantity, unit_price, amount)                  [H]
                   実行予算。受注時に工種×原価区分で確定
CostTransaction  (company, site, work_type, cost_category,
                  amount, transaction_date,
                  source_type, source_id, supplier FK nullable,
                  manhours nullable)
                   統一原価データ（v0.1 §5.6 を初期実装に昇格）
                   INDEX(company, site, work_type, cost_category)
```

CostTransaction の生成規則（自動仕訳）:

| source_type | 発生元 | 生成タイミング | 原価区分 | 金額 |
|---|---|---|---|---|
| daily_report | DailyReport | 承認時 | 労務費 | work_hours × Worker.hourly_cost |
| po_item | PurchaseOrderItem | 検収時 | 材料費 | quantity × unit_price |
| outsourcing | 外注実績（手入力） | 登録時 | 外注費 | 入力値 |
| expense | 経費（手入力） | 登録時 | 経費 | 入力値 |

- 発生元の訂正時は逆仕訳＋再仕訳を生成し、CostTransaction 自体は不変（追記のみ）とする。原価集計の監査可能性を担保する。
- Site の粗利 = contract_amount − Σ CostTransaction.amount。粗利率を案件一覧・ダッシュボードの主指標とする。

### 5.8 リレーション要約

| テーブル | 主な関連先 | 役割 |
|---|---|---|
| Company | 全テナント帰属テーブル | テナント起点 |
| Site | Process / DailyReport / PurchaseOrder / BudgetItem / CostTransaction | 全業務データの起点 |
| DailyReport | Worker / Site / Process / Material | 実績のハブ。労務費の生成元 |
| CostTransaction | 各実績テーブル (source_type/source_id) | 統一原価。分析・AIの唯一の参照先 |

## 6. 権限設計

- ロールは Django Group（admin / manager / worker）+ Permission。独自権限テーブルは作らない。
- Django admin はSaaS運営者（自社）専用とし、**テナントユーザーには開放しない**。テナント向け管理機能（自社ユーザー管理・マスタ管理）は専用画面として実装する。
- テナント内の可視範囲: worker は自分の日報のみ編集可・自現場,材料管理のみ閲覧可。manager は自社全データ。詳細マトリクスは実装時に `docs/permissions.md` へ確定する。

## 7. 非機能要件

- **監査**: [H] 付与テーブルは全変更履歴を自動記録。HistoryRequestMiddleware で変更者を記録。
- **マイグレーション**: expand / contract 方式（追加→両対応デプロイ→データ移行→次リリースで削除）。改名・NOT NULL 追加の一発適用を禁止。CI で `makemigrations --check` を常時実行。
- **バックアップ**: 日次フル + WAL。四半期ごとにリストア訓練を実施し手順書を更新。
- **稼働監視**: `/health/`（DB到達性込み）。デプロイスクリプトは 200 を確認できるまで旧バージョンを維持。
- **性能目安**: 日報一覧・案件一覧は 100テナント×5年分データで 1秒以内（ページネーション必須、N+1 は select_related/prefetch_related で排除)。

## 8. インフラ段階計画（v0.1踏襲・要約）

| フェーズ | 契約社数 | 環境 |
|---|---|---|
| PoC / デモ | 1〜3社 | ミニPC/小型VPS（本番ホスティングには使用しない） |
| 初期ローンチ | 5〜15社 | VPS 1〜2台 + 日次バックアップ外部保管 |
| 成長期 | 15〜50社 | クラウド + マネージドDB（RDS等） |
| 目標到達 | 50〜100社 | マネージドコンテナ / オートスケール |

行レベル分離採用により、全フェーズでDBは1系統のまま移行できる。

## 9. 開発フェーズ計画

| マイルストーン | 内容 | 完了条件 |
|---|---|---|
| M1 基盤 | tenants / accounts / masters / core、テナント分離機構、CI、admin | 越境テスト含む全テスト green |
| M2 日報+現場 | sites / schedule / reports、日報UX、承認フロー | 実データでの入力検証 |
| M3 原価集約 | costs、労務費自動仕訳、実行予算、予実対比画面 | 粗利率が案件一覧に出る |
| M4 材料 | materials 受発注、材料費自動仕訳 | 検収→仕訳の自動生成 |
| M5 人材 | workers 詳細 / evaluations | 日報実績との連動 |
| M6 分析 | ダッシュボード、工種別粗利、歩掛実績反映 | ここまで統計処理のみで実現 |
| M7 AI | 類似案件検索、見積ドラフト、施工計画ドラフト | 出力は下書き。有資格者承認を必須とする |

利益率改善の主効果は M3〜M6 で発生する。M7 は M6 までのデータ品質に完全に依存する。

## 10. Claude Code 向け開発規律（CLAUDE.md へ転記）

1. Django 5.2 LTS / Python 3.12 を変更しない。依存追加は ADR 必須。
2. 業種名をコード・クラス名・分岐に書かない。業種差異は WorkType マスタで表現する。
3. テナント帰属モデルは必ず TenantModel を継承し、CompanyScopedManager を通す。unscoped の使用は理由をコメントで明記。
4. 新規モデルには simple-history を付与し、admin 登録・テナント越境テスト・マイグレーションを同一PRに含める。
5. 予算・原価に触れるコードは、工種×原価区分の粒度を崩さない。粒度を落とす変更は禁止。
6. main へ直接コミットしない。PR + CI green + レビュー1名。
7. マイグレーションは expand/contract。破壊的変更を単一リリースで行わない。
8. 金額計算は Decimal のみ。float 禁止。タイムゾーンは USE_TZ=True 前提で aware datetime のみ。
9. 設計判断をしたら docs/adr/ に1ファイル追加する。

## 11. 今後の検討事項（v0.1から更新）

- 内装・解体拡張時の追加モジュール（7〜12）の業種別マトリクス
- コア＋アドオン課金の価格設定（v0.1 §4.2 の方針を維持）
- 権限詳細マトリクス（docs/permissions.md）
- 日報オフライン入力（v1.1）
- M7 のユースケース詳細（原価予測・異常検知・類似案件検索）の要件定義

## 付録A: v0.1 からの主な変更点

| 項目 | v0.1 | v0.2 |
|---|---|---|
| 技術スタック | 未定 | Django 5.2 LTS + PostgreSQL 16 に決定 |
| マルチテナント物理方式 | 未決（検討事項） | 行レベル分離に決定。越境テスト常設を要件化 |
| industry_subtype | 文字列区分 | WorkType 階層マスタに昇格 |
| sites | 現場テーブル | Site に案件情報（受注金額・状態）を統合 |
| cost_transactions | 将来拡張 | 初期実装（M3）に昇格。生成規則・不変性を定義 |
| 実行予算 | 記載なし | BudgetItem を新設。工種×原価区分の予実対比を主機能化 |
| role | users.role カラム | Django Group に変更 |
| 開発規律 | 記載なし | 第10章として新設（Claude Code 入力用） |
