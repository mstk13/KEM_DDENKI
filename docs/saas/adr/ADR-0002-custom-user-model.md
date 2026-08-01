# ADR-0002: カスタムユーザーモデルを初回 migrate 前に定義する

## ステータス
承認

## コンテキスト
Django の AUTH_USER_MODEL は初回マイグレーション後に変更するのが極めて困難。
マルチテナント SaaS では User に company FK が必須。

## 決定
`accounts.User` を `AbstractUser` から継承し、`company` FK・`employee_no`・`department` FK を追加する。
`AUTH_USER_MODEL = "accounts.User"` を settings.py に設定する。
**初回 `migrate` 実行前に必ずこのモデルを定義する。**

ロールは独自カラムを廃止し、Django Group（admin / manager / worker）で表現する。

## 結果
- テナント帰属がユーザーレベルで保証される
- Django の認証・権限システムをそのまま活用できる
- 後からのモデル変更リスクを回避
