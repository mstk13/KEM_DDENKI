# ADR-0004: AI分析基盤の導入

## ステータス

承認

## コンテキスト

KEM_DDENKIの原価管理・工期管理モジュールに蓄積された過去データを活用し、
コスト最適化提案と工程作成・管理を行うAI分析機能が必要になった。

## 決定

### アーキテクチャ

1. **LLM推論（コスト最適化提案・工程提案）**: Claude API（Haiku/Sonnet）を使用
2. **数値予測（予算超過率・工期遅延確率）**: ローカルML（LightGBM等）を使用
3. **AI入出力ログ**: `AILog`モデルで全呼び出しを記録し、将来のファインチューニング用データセットとする
4. **ユーザーフィードバック**: `AIFeedback`モデルで出力品質を追跡

### 新規依存

- `anthropic` (Claude API クライアント) — Phase 2で追加予定
- `lightgbm`, `scikit-learn` — Phase 1で追加予定

### データフロー

```
PostgreSQL → data_collector.py → prompt_builder.py → Claude API → AILog
                                                                    ↓
                                                              AIFeedback（ユーザー評価）
```

## 理由

- Claude APIはローカルLLMより推論品質が高く、初期投資ゼロ、運用負荷なし
- 数値予測タスクはLLMより従来MLの方が適切（コスト効率・精度とも）
- AILogによるログ基盤を先に構築することで、将来のモデル最適化に必要なデータを初日から蓄積できる

## 影響

- `apps.ai` アプリを新規追加
- `INSTALLED_APPS` と URLconf に登録
- AILog, AIFeedback の2モデルとマイグレーション追加
