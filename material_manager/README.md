# 工事材料管理システム

工事現場ごとに、見積もりの品目と実際の発注状況を比較管理するWebアプリ。

## 機能

- 現場（案件）の登録・管理
- 品目別の見積もり明細登録
- 発注登録（分割発注対応）
- 見積もり vs 発注の消化率比較
- 品目クリックで発注履歴ドリルダウン（誰が/いつ/どこから/いくら）
- 単価履歴の自動蓄積（将来のAI見積もり自動生成に向けて）

## データ構造

KEM_DDENKI（入札案件管理）と統合可能な設計:

- `project` — 入札〜施工〜完了の全ライフサイクル
- `item_master` — 全現場共通の品目マスタ
- `supplier` — 仕入先マスタ
- `estimate_header` / `estimate_line` — 見積もり（版管理+品目別明細）
- `order` — 発注レコード（分割対応）
- `price_history` — 単価履歴（AI学習データ）

## セットアップ

全アプリ共通のセットアップ手順は **[セットアップガイド（docs/setup_guide.md）](../docs/setup_guide.md)** を参照してください。

> 個別に起動する場合: `cd material_manager && pip install -r requirements.txt && python -c "from db import init_db; init_db()" && python app.py`

## 将来計画

- KEM_DDENKI との統合（入札→受注→材料管理の一気通貫）
- AI見積もり自動生成（過去の見積もり+発注+単価履歴を学習）
- 帳票PDF出力
- ユーザーログイン
- Excelインポート
