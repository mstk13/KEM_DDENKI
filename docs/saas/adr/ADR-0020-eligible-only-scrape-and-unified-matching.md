# ADR-0020: 資格を満たす案件だけ取り込む／全省庁統一資格を判定に使う

## ステータス

承認

## コンテキスト

海上自衛隊 横須賀基地の入札公告ページ（`msdf_yokosuka`）から案件を取り込み、
登録済みの入札参加資格で参加できるものだけを入札案件に登録したいという要望が出た。

調べた結果、次の3つの問題があった。

1. 防衛省系スクレイパー（`mod_base`）が依存する `beautifulsoup4` と、
   共通モジュールが依存する `requests` が `pyproject.toml` に無く、
   本番・開発のコンテナで `ModuleNotFoundError` になり動いていなかった
2. 横須賀基地の公告は「物品の販売」「役務の提供等」「物品の買受け」の
   全省庁統一資格で参加するものが大半だが、ADR-0011 で全省庁統一資格は
   判定から除外しており、全件「対応する資格がありません」になる
3. スクレイパーは工事種別を「物品・役務」の大枠でしか付けず、
   発注機関も「海上自衛隊 横須賀基地」なので、防衛省の工事資格にも当たらない

## 決定

### 1. `requests` と `beautifulsoup4` を依存に追加する

既にコードが使っている（`apps/bids/scrapers/__init__.py`、`mod_base.py`）ものを
宣言し忘れていただけなので、新しい依存の採用ではなく修正として扱う。
Dockerfile は `pyproject.toml` の dependencies からインストールするので、
次回デプロイで直る。

### 2. 公告 PDF から「資格の種類」を読み、判定の入口を切り替える

自衛隊の公告は資格要件を定型で書く。

- 物品・役務: `防衛省競争参加資格（全省庁統一資格）「物品の販売」のＤ等級以上`
- 工事: `「建築一式工事」又は「管工事」で級別の格付けを受け … Ｃ・Ｄ等級以上`

`announcement.extract_sections()` が `required_issuer_type`（全省庁統一資格／防衛省）と
`required_category`（種類または業種の列挙）を返すようにし、`check_project()` は

- `required_issuer_type == 全省庁統一資格` なら、発注機関ではなく統一資格の
  種類・等級下限・有効期限で判定する（`_check_unified`）。営業品目は
  公告の資格要件に書かれないので見ない
- それ以外は、`required_issuer_type` があればそれを発注機関として、
  `required_category` があればそれを業種として既存の判定に流す

ADR-0011 の「統一資格を発注機関の突き合わせから除く」はそのまま残る。
統一資格で判定するのは公告が明示している案件だけで、i-ppi の工事案件が
統一資格に誤って当たることはない。

### 3. `ScrapeTarget.only_eligible` で「資格を満たす案件だけ登録」を選べる

既定は従来どおり全件登録。オンにしたターゲットは、新規案件を登録する前に
公告 PDF を読み `check_project()` で判定し、参加できる案件だけ登録する。

- 資格を満たさない案件は登録しない（`資格不足N件`）
- 公告が読めない・資格要件が書かれていない案件は登録しない（`判定不能N件`）。
  取りこぼしに気づけるよう、件数は `last_result` と戻り値に出す
- 判定に使った要件（種類・等級・工事概要・参加要件）は登録時に一緒に保存する。
  公告の種類が分かった案件は工事種別「物品・役務」を種類（物品の販売など）で置き換える

売払い案件（物品の買受け）は従来どおり件名で除外したままにする。
資格上は参加できるが、鉄屑・廃油などの売払いは業務の対象外という判断が先にあるため。

## 影響

- `pyproject.toml` に `requests`、`beautifulsoup4`
- `apps/bids/announcement.py`: `extract_unified_requirement`、`extract_mod_works_categories`
- `apps/bids/qualification.py`: `_check_unified`、公告の資格種別・業種の優先
- `apps/bids/services.py`: `_judge_before_register`、`run_scrape` の見送り集計
- `apps/bids/models.py`: `ScrapeTarget.only_eligible`（マイグレーション 0016）
- テスト `tests/test_bids_eligible_scrape.py`
- 運用: 横須賀基地の ScrapeTarget を `only_eligible=True` で登録する（開発・本番それぞれ）
