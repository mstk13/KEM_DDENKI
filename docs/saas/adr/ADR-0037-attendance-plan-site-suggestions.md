# ADR-0037: 出社予定の「場所・メモ」に登録済みの現場名を候補として出す（自由入力は残す）

## ステータス

採用（2026-09-11）

## コンテキスト

出社予定（`AttendPlan`、ADR-0023）の「場所・メモ」（`note`）は自由入力で、現場マスタとは結びついていない。
プロダクトオーナーから次の要望があった（2026-09-11）。

> 出社予定の記入で、各日の場所・メモに、現場として登録されているものを候補として出したい。
> 候補の中にない場合は自分で記入できるようにしたい。

入力欄は2か所ある。

| 画面 | 入力欄 |
|---|---|
| 月グリッド（`attendance:plan_board`） | マスをダブルクリックで開くダイアログの「場所・メモ」（`#plan-dialog-note`） |
| 日シート（`attendance:plan_day`） | 作業員ごとの「現場名・行先」（`note_<作業員ID>`） |

また、ホームの現場カードの参加者（ADR-0036）は、行き先を現場名と突き合わせて決めている。
手で打つと表記が揺れて一致しないことがあるので、候補から選べると参加者に確実に載る。

## 決定

1. **HTML 標準の `<datalist>` で候補を出す**。入力欄に `list` を付けるだけで、候補を出しつつ、
   候補にない文字もそのまま入力・保存できる。保存処理・`note` の持ち方（自由入力の文字列）は変えない
2. 候補は `attendance.plans.site_name_suggestions(company)` が返す。
   - 対象は **施工中・受注済・見積中** の現場。完工・請求済・中止の現場へ行く予定は立てないので出さない
   - 施工中 → 受注済 → 見積中 の順、同じ状態の中は現場名順。同じ名前は1つにまとめる
   - 自社の現場だけ
3. `<datalist>` はテンプレートの部品 `attendance/partials/site_name_datalist.html` にし、2つの画面で共有する
4. ダイアログには「登録済みの現場から選べます。候補にない場合はそのまま入力してください。」と添える

## 捨てた選択肢

- **`<select>` で現場を選ばせ、「その他」を選んだら入力欄を出す**: 自由入力のたびに2操作になる。
  出張の行先（「大阪 支店」）や社内の用事など、現場以外の行き先も多い
- **`note` を現場 FK に変える**: 現場以外の行き先が書けなくなる。既存データの移行も要る
- **JavaScript の補完ライブラリを入れる**: 依存が増える（CLAUDE.md ルール1で ADR が要る）。
  `<datalist>` で要望は満たせ、スマホでもキーボードの上に候補が出る

## 影響

- 追加: `apps/attendance/plans.py` の `site_name_suggestions` / `SUGGESTED_SITE_STATUSES`
- 追加: `templates/attendance/partials/site_name_datalist.html`
- 変更: `apps/attendance/views.py`（`plan_board` / `plan_day` のコンテキストに `site_names`）
- 変更: `templates/attendance/plan_board.html`（ダイアログの入力欄）、`templates/attendance/plan_day.html`（作業員ごとの入力欄）
- 追加: `tests/test_attendance_plan_site_suggestions.py`
- モデル・マイグレーションなし。保存される値は今までどおり入力された文字列
