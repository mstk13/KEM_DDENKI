# ADR-0098: lint の設定はリポジトリのルート1か所に置く

日付: 2026-09-19
状態: 採用

## 背景

lint（ruff）の設定は `saas/pyproject.toml` の `[tool.ruff]` にしか無かった。
ruff は対象ファイルから上へ向かって設定を探すため、これは
**`saas/` の中で流したときだけ効く設定**だった。

その結果、次のことが起きていた。

- **`saas/` の外の Python は、どの設定にも当たらない。**
  `api/main.py`（KEIHI 連携の REST API）は ruff の既定値でしか見られない。
- **CI もそこを見ていない。** `ci-saas.yml` は `paths: ['saas/**']` で絞っており、
  lint も `working-directory: saas` で `ruff check .` を流す。`api/` は
  一度も検査されていなかった。実際に未使用 import（`fastapi.Query`）が残っていた。
- **リポジトリのルートで `ruff check .` を流すと、CI と結果が違う。**
  設定が見つからないので ruff の既定値（line-length 88・既定ルールのみ）になる。
  プロジェクトの決まりは line-length 99 / `E,F,I,UP,B,SIM` なので、
  手元で緑でも CI で落ちる、逆に手元で赤でも CI は緑、という状態だった。

設定を書き写して2か所に置く手は採らない。片方だけ直されて食い違う。
食い違いは「どちらが正か分からない」ため、無い状態より悪い。

## 決定

**lint の設定はリポジトリのルートの `ruff.toml` だけに置く。**

- `saas/pyproject.toml` の `[tool.ruff]` は削除し、ルートを見るよう注記を残す。
  `[tool.ruff]` を持たない `pyproject.toml` は ruff に無視されるので、
  `saas/` の中で `ruff check .` を流してもルートの `ruff.toml` が効く。
- `src = [".", "saas", "api"]` を入れる。isort（`I`）が
  「自分のコードか外部パッケージか」をこれで判断するため、`saas` を入れないと
  `apps/...` `config/...` が外部扱いになり、**`saas/` の中で流したときだけ**
  import 順が 101 箇所ずれて落ちる。
- `per-file-ignores` のパターンは `**/` から書く。`apps/materials/services.py`
  のような相対パターンは「どのディレクトリで ruff を起動したか」で解釈が変わり、
  `saas/` の外から流すと除外が効かなくなる（E501 が復活する）。
  除外の理由（約款の条文・LLM のプロンプト）は元のコメントのまま持ち越す。
- **リポジトリ全体を見る lint ワークフロー**（`.github/workflows/ci-lint.yml`）を
  足す。`paths` を付けず、全ての push / PR で `ruff check .` をルートで流す。
  `ci-saas.yml` の lint は二重になるので外す。
- ruff のバージョンは `saas/pyproject.toml` の dev extra **だけ**で宣言する。
  ワークフローは `tomllib` でそこから読む（Dockerfile が本体依存を読むのと同じ手）。
  ワークフローに書き写すと、片方だけ上げたときに CI と手元で結果が変わる。
- コンテナには `saas/` の中身しか入らないため、`docker-compose.yml` の web に
  `../ruff.toml:/app/ruff.toml:ro` を足す。開発者ガイドの
  「使い捨てコンテナで `ruff check .`」が CI と同じ結果になる。
  アプリの実行時には使わない設定なので、本番でも無害。
- あわせて `.editorconfig` を置く。改行 LF（`.gitattributes` と同じ理由）と
  行長 99（`ruff.toml` と同じ値）をエディタ側にも効かせる。

### テストの設定

`[tool.pytest.ini_options]` に `testpaths = ["tests"]` を足す。
これが無いと引数なしの `pytest` が `apps/` 以下まで収集し、
CI の `pytest tests/` と結果が変わる。設定は `saas/pyproject.toml` に置く
（Django の設定モジュールに依存するため、`saas/` の外には出せない）。

### mypy は流さない（既知の穴）

`[tool.mypy]` は `strict = true` で置かれているが、**CI でもローカルでも
誰も流していない**。この ADR では流さない。strict のまま全体にかけると
現状は大量に落ちるため、入れるなら別の作業として範囲を絞って進める。
設定があるのに誰も流していない状態を、知らずに信用しないよう
`pyproject.toml` に注記を残す。

## 結果

- どのディレクトリで `ruff check .` を流しても同じ結果になる
  （リポジトリのルート・`saas/`・コンテナの `/app`）
- `api/` と `tools/` の Python も CI で検査される。
  この ADR の作業で見つかった 4 件（未使用 import 1・行長 3）は同時に直した
- lint の設定を変える場所は1つ。行長だけは `.editorconfig` にも同じ値があるので、
  変えるときは両方直す（`.editorconfig` に注記あり）
- mypy は依然として流れていない。穴は穴として明示した
