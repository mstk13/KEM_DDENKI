# KEM_DDENKI API

KEIHIなどの外部アプリと連携するためのREST APIサーバー。

> [!NOTE]
> ポートは 8002 を使います。8001 は開発環境の Django アプリが使用中のため、
> そのまま 8001 で起動するとサーバーPC上で衝突します。
> 使用中のポートは [サーバー運用ガイド](../docs/server_operations.md) を参照してください。

## 起動

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8002
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

http://localhost:8002/docs
