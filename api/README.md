# KEM_DDENKI API

KEIHIなどの外部アプリと連携するためのREST APIサーバー。

## 起動

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

## エンドポイント

- `GET /api/v1/sites` - 現場一覧
- `GET /api/v1/sites/{id}` - 現場詳細
- `GET /api/v1/projects` - プロジェクト一覧
- `GET /api/v1/projects/{id}` - プロジェクト詳細
- `GET /api/v1/projects/{id}/costs` - プロジェクト原価
- `POST /api/v1/expenses/sync` - KEIHI経費データ同期
- `GET /api/v1/health` - ヘルスチェック

## APIドキュメント

http://localhost:8001/docs
