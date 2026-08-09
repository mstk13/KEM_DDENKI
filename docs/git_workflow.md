# Git 運用ルール

> 手順の詳細は **[開発者ガイド](developer_guide.md)** にまとめています。
> このページはブランチの役割とルールだけを扱います。

## ブランチの役割

```
main       ← 本番環境（マージすると最大2分で本番に自動反映）  PM承認必須
 ↑ Pull Request
developer  ← 開発環境（pushすると最大2分で開発環境に自動反映） 開発者全員
```

| ブランチ | 誰が push できるか | 反映先 |
|---------|------------------|--------|
| `developer` | 開発者全員 | https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/ |
| `main` | 誰も直接 push しない（PR のマージのみ） | https://desktop-rmsk0vg.tail8efe0d.ts.net/ |

**編集は必ず `developer` で行います。**

`feature/xxx` のような作業ブランチを切っても構いません。その場合は `developer` に PR を出すか、
`developer` にマージしてから push してください。

## 絶対にやらないこと

```bash
git push origin main          # ❌ 本番に無審査で反映される
git push --force              # ❌ 他の人のコミットが消える
git switch -C developer ...   # ❌ developer は常設ブランチ。作り直さない
```

`developer` は他の開発者と共有する常設ブランチです。取り込む（merge / pull）ことはあっても、
作り直すことはありません。

## main へのマージ

1. `developer` で開発環境の動作を確認する
2. `developer` → `main` の Pull Request を作る
3. CI（ruff / マイグレーション整合性 / テスト）が緑になるのを待つ
4. **PM が Approve する**
5. PM がマージする → 本番に自動反映

このルールを GitHub 側で強制する設定は [main ブランチ保護の設定](branch_protection_setup.md) を参照してください。
（未設定のあいだは、ルールは強制されずお願いベースになります）

## コミットメッセージ

`種類(場所): 内容` の形にします。詳細は [開発者ガイド](developer_guide.md#4-コミットメッセージ) を参照。

## 確認コマンド

```bash
git branch --show-current                        # 今どのブランチにいる？
git status                                       # 未コミットの変更は？
git log --oneline origin/developer..HEAD         # developer に未反映の自分のコミット
git log --oneline origin/main..origin/developer  # 本番に未反映の変更
```

**push する前に1行目を確認する癖をつけてください。**

---

## 過去の経緯

### 2026-07: ブランチの分岐事故

7/23に一時的な作業用として作った `deploy-update` を削除し忘れ、7/27にそのブランチ上で作業を再開したため、
main と完全に分岐しました（19ファイルでコンフリクト）。同じ機能が両方に別々のコミットとして存在する
状態になり、7/28に整理しました。

**原因は「合流し忘れた古いブランチの上で作業したこと」です。**
作業開始時に必ず `git pull origin developer` を実行するのは、これを防ぐためです。

### 2026-08: developer が 26 コミット遅れていた

`developer` に独自コミットが無いまま `main` だけが進み、開発環境として機能しない状態になっていました。
`main` の内容で `developer` を早送りして揃えています。

`main` にマージしたあとは、`developer` を `main` に追いつかせてください。

```bash
git switch developer
git pull origin main
git push origin developer
```
