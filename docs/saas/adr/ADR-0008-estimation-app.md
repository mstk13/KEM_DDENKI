# ADR-0008: 積算アプリ（estimation）の設計

## ステータス

承認

## コンテキスト

公共工事の入札にあたり、発注者の積算単価と自社の仕入単価のギャップ
（＝応札余力）を定量化するシステムが必要になった。

3つのデータソース（発注者の数量書、積算基準書、仕入先の見積書）が
それぞれ異なる品名体系を使用しており、同一物理品目の突合（名寄せ）が
中核課題となる。

仕様書（06-積算システム仕様.md）は FastAPI + SQLAlchemy を前提に
書かれているが、KEM_DDENKI は Django 5.2 で構築されているため
Django のパターンに適合させる。

## 決定

### 1. Phase 1 のスコープ

3モデル（EstimationItem, ItemAlias, Orderer）を `apps.estimation` として
新規追加する。名寄せのレビューキューUIを中核機能とする。

労務単価・歩掛・共通費・内訳書・差分分析は Phase 2 以降。

### 2. EstimationItem と Material の関係

- EstimationItem は `materials.Material` への Optional FK を持つ（SET_NULL）
- Material は社内購買カタログ、EstimationItem は発注者の積算体系に合わせた
  品目定義。同一物理品目でも視点が異なる
- 労務費項目など Material に対応しないものもあるため、FK は必須にしない
- Material を複製・拡張するのではなく、別モデルとして橋渡しする設計

### 3. 名寄せアーキテクチャ

- ItemAlias テーブルで N:1 の対応を管理
- 正規化モジュール（`services/normalization.py`）は Django 非依存の
  純粋関数として実装。テスト容易性と他アプリでの再利用性を確保
- マッチングはカスケード戦略:
  コード一致(100) → 正規化名一致(90) → 仕様一致(70) → 未マッチ(pending)
- 信頼度90未満の自動マッチ結果は必ず人間のレビューを要求

### 4. Orderer と Customer の関係

- Orderer は `masters.Customer` への Optional FK を持つ
- Orderer は積算基準・体系情報を持つ公共発注機関に特化したモデル
- Customer は汎用取引先であり、積算固有の属性を持たせない

### 5. 仕様書との差異

| 仕様書の要件 | 実装での対応 | 理由 |
|---|---|---|
| UUID 必須 | BigAutoField（既存パターン） | 既存15アプリが BigAutoField。統合時に追加可能 |
| deleted_at 論理削除 | is_active + simple-history | 既存パターンに合わせる |
| audit_log テーブル | HistoricalRecords() | 既に全アプリで使用中 |
| external_ref テーブル | Phase 2 以降 | 統合先が未確定 |
| LLM マッチング | Phase 2 以降 | まず確定的なマッチングで精度を検証 |

## 影響

- 新規テーブル6つ（3モデル + 3 historical テーブル）、expand-only
- 既存テーブルへの変更なし
- Phase 2 で EstimationStandard, WorkRate, LaborRate, OverheadRule,
  BoqLine, CostComparison を追加予定
- `services/normalization.py` は `bids` や `materials` でも再利用可能
