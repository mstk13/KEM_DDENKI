# ADR-0019: 全省庁統一資格の省庁別許可内容を別表として持つ

## ステータス

承認

## コンテキスト

全省庁統一資格は「物品の販売」「役務の提供等」「物品の買受け」の3区分について
等級・点数・営業品目が全適用機関で共通だが、どの省庁・機関に適用されるかは
資格審査結果通知書とは別の一覧（Excel「省庁別許可内容一覧」シート）でしか
確認できなかった。入札参加資格の画面で、既存の発注機関別の資格一覧と並べて
参照したいという要望が出た。

## 決定

### 1. 既存の `Qualification` に混ぜず、`UnifiedQualification` を新設する

`Qualification` は「発注機関 × 業種区分」で1行を持ち、案件との突き合わせ
（`qualification.py`）の元データになっている。ADR-0011 で全省庁統一資格は
突き合わせから除くと決めており、31機関分を `Qualification` に入れると
突き合わせ対象が増えて誤判定の元になる。

省庁別の表は参照用に分け、`UnifiedQualification` として機関ごとに1行持つ。
列は Excel の必要項目のみ（省庁・機関名、3区分の等級・点数、
物品の販売と役務の提供等の営業品目）。「物品の製造」は資格登録が無く
全機関で「―」なので持たない。押印・押印者・備考も画面に出さないので持たない。

### 2. Excel からの取り込みは管理コマンドで行う

31機関分を画面から手入力するのは現実的でなく、機関の追加・変更も
元の Excel を更新して取り込み直す運用になる。`import_unified_qualifications`
コマンドで Excel を読み、`(company, agency)` をキーに更新または作成する。
`--replace` で全置換もできる。

列の位置は見出し行の文言（「省庁・機関名」「物品の販売」＋「等級/点数」など）
から決め、列の並びが変わっても追従する。「―」は資格なしの意味なので空扱いにする。

### 3. 画面は既存の資格一覧の下に別表として置く

入札参加資格の一覧画面（`/bids/qualifications/`）で、既存の表の下に
「全省庁統一資格 省庁別許可内容一覧」を2段見出しの表で表示する。
1件ずつの編集・削除は既存の資格と同じ流儀（フォーム画面と confirm 付き削除）。

## 影響

- `apps/bids/models.py` に `UnifiedQualification`（simple-history 付き）、マイグレーション 0015
- `apps/bids/importer.py` に `import_unified_excel`、管理コマンド `import_unified_qualifications`
- `/bids/qualifications/unified/...` の登録・編集・削除
- テスト `tests/test_unified_qualification.py`（読み込み・コマンド・越境・画面）
- 本番反映後に `python manage.py import_unified_qualifications <Excel>` を1回実行する必要がある
