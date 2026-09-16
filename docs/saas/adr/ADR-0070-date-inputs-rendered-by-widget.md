# ADR-0070: 日付欄はフォームのウィジェットで描く（編集で日付が消えるのを直す）

## ステータス

採用（2026-09-16）

## コンテキスト

プロダクトオーナーの報告（2026-09-16）: 現場管理などで日付を一度登録したあと、その案件を
もう一度編集すると、前に入れた日付が空欄になっている。気づかず保存すると日付が消える。

原因はテンプレートの書き方だった。

- 編集画面の日付欄は `<input type="date" ... value="{{ form.start_date.value|default:'' }}">` と
  **手書き**していた
- `BoundField.value()` が返すのは `datetime.date` オブジェクトであって文字列ではない。
  Django のテンプレートは変数を出すときに値をロケールの**表示**書式に直すので、
  `LANGUAGE_CODE = "ja"` では `2026年9月16日` が埋まる
- `<input type="date">` は `YYYY-MM-DD` しか値として受け取らない。解釈できない値は
  ブラウザが捨てるため、欄は**空**で表示される。そのまま保存すると空で上書きされる
- 新規登録と、入力エラーで描き直したときは、値が送信された文字列（`2026-09-16`）なので
  素通りする。**編集画面を開いたときだけ**起きるので気づきにくかった

一方、フォーム側の `forms.DateInput(attrs={"type": "date", ...})` は
`DATE_INPUT_FORMATS[0]`（`%Y-%m-%d`）で値を書き出すため、同じ値が正しく入る。
つまりウィジェットは最初から正しく、テンプレートがそれを使っていなかった。

対象は 7 テンプレート・12 箇所（現場、見積取込、工程フェーズ、マイルストーン、
人員アサイン、開発管理のプロジェクト・タスク）。

## 決定

1. **フォームの日付欄はウィジェットで描く**。テンプレートには `{{ form.start_date }}` と書き、
   `type="date"` や `value` を手書きしない。`class="form-control"`・`id`・`required` は
   ウィジェットと `BoundField` が付けるので、見た目と `<label for>` は変わらない
2. 表示書式は `DateInput` の既定（`%Y-%m-%d`）に任せる。テンプレート側で
   `|date:"Y-m-d"` を足す方法は採らない（下記）
3. テンプレートを横断して見張るテストを置く。`templates/` 以下の `.html` に
   `type="date"` と `{{ form.*.value }}` を同時に持つ `<input>` があれば落とす
   （`tests/test_date_value_kept_on_edit.py`）

## 捨てた選択肢

- **`{{ form.start_date.value|date:"Y-m-d" }}` にする**: 編集画面は直るが、入力エラーで
  描き直すときに値が**文字列**なので `date` フィルタが空文字を返し、今度は入力途中の値が消える。
  日付オブジェクトと文字列の両方を通すには `|default:` を重ねる必要があり、12 箇所に
  同じ小細工が散る
- **`USE_L10N` を切る / `LANGUAGE_CODE` を変える**: 表示書式は日本語のままにしたい。
  全画面の日付・数値の見え方に波及する
- **カスタムの `DateInput` サブクラスに `format` を明示する**: ウィジェットは既定で正しく、
  直すべきはテンプレート側。フォームを触っても手書き `value` は直らない

## 影響

- モデル・マイグレーションの変更なし。テンプレートのみ
- 変更したテンプレート: `sites/form.html`, `sites/import.html`,
  `schedules/phase_form.html`, `schedules/milestone_form.html`,
  `schedules/assignment_form.html`, `devkanri/project_form.html`, `devkanri/task_form.html`
- 絞り込み条件などフォームを通さない日付欄（`reports/list.html`,
  `materials/purchase_history.html` など）は、ビューが `|date:'Y-m-d'` で文字列にして
  渡しているため対象外。ガードテストも `form.*.value` を持つものだけを見る
- **既に日付が消えてしまった案件のデータは戻らない**。入れ直しが必要
