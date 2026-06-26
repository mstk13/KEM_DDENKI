# KEM_DENKI

株式会社ケンモチ電機の社内ツールを管理するリポジトリです。

## 概要

電気工事会社向けの業務効率化ツール群を集約・管理します。各ツールの仕様書・ソースコード・ドキュメントをここで一元管理します。

## ツール一覧

| ツール | 内容 | 実装 | 仕様書 |
|--------|------|------|--------|
| 入札案件管理システム | 入札案件の収集・管理・原価分析を行うWebアプリ（Streamlit + SQLite） | [bid_manager/](bid_manager/) | [docs/spec.md](docs/spec.md) |

## ディレクトリ構成

```
.
├── README.md
├── docs/                 # 各ツールの仕様書・ドキュメント
│   └── spec.md           # 入札案件管理システム 仕様書
└── bid_manager/          # 入札案件管理システム（実装）
    ├── app.py            #   Streamlit メインアプリ
    ├── database.py       #   SQLite スキーマ・CRUD
    ├── scraper.py        #   案件スクレイピング
    ├── notifier.py       #   メール通知
    ├── scheduler.py      #   定期実行
    ├── config.py         #   設定
    ├── seed.py           #   デモデータ投入
    └── requirements.txt
```

セットアップと使い方は [bid_manager/README.md](bid_manager/README.md) を参照。
