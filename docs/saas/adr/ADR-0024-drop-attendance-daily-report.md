# ADR-0024: 勤怠日報を廃止し、実績を日報（reports）に一本化する

## ステータス

承認

## コンテキスト

同じ「作業員が何日にどこで何時間働いたか」という実績が、2つのモジュールに
別々のテーブルで入っていた。

| | 勤怠日報 `attendance` | 日報 `reports` |
|---|---|---|
| ヘッダ | `AttendReport` | `DailyReport` |
| 現場 | `site_name`（**文字列**） | `site`（`Site` への FK） |
| 明細 | `AttendEntry`（作業員×時刻） | `DailyReport` 自体が作業員単位 |
| 工種 | なし | `work_type`（`WorkType` FK） |
| 原価 | 繋がらない | 承認時に `CostTransaction`（労務費）を自動生成 |

二重入力になるだけでなく、勤怠日報側は現場が文字列のため現場マスタと突合できず、
工種も持たないので原価の粒度（工種 × 原価区分）に乗らない。実績を集めても
原価・積算・工期のどこにも流れない行き止まりのテーブルだった。

月次集計はさらに3箇所に同じクエリが散っていた。

- `attendance:summary` … `AttendEntry` から集計する画面
- `reports:monthly_summary` … `DailyReport` から集計する画面（テンプレートの
  見出しは「勤怠集計」）
- `workers.services.get_attendance_summary()` … `reports.services.get_monthly_summary()`
  とクエリも annotate も同一。どこからも呼ばれていない死にコード

## 決定

### 1. 勤怠日報とその周辺画面を削除する

`AttendReport` / `AttendEntry` を使う画面・URL・フォーム・admin を削除する。
対象は 勤怠日報の一覧・登録・詳細・編集・削除、個人別一覧、従業員別記録、
月次サマリ の8ビュー。`utils.calc_attendance()` はこのうち登録・編集の2ビュー
専用だったのでファイルごと削除する。

`attendance` アプリ自体は残す。`AttendPlan`（出社予定）は「これから誰がどこへ
行くか」を先回りで埋める別機能で、実績とは重複しない。`AttendSettings` は
出社予定が所定始業・終業時刻の既定値として参照しているため残す。

`/attendance/` の入口は勤怠日報一覧から出社予定へ変える。

### 2. 月次サマリは新規に作らず、既存の日報側の画面を指す

`reports:monthly_summary`（`/reports/monthly/`）が作業員別の
出勤日数・通常時間・残業時間・合計時間を `DailyReport` の承認済データから
既に出している。サイドバーの「月次サマリ」はこれを指すだけにした。
勤怠側に同じ集計のビューを新設すると、同一クエリの4つ目の複製になる。

あわせて、呼ばれていない `workers.services.get_attendance_summary()` を削除する。
`reports.services.get_monthly_summary()` と同じものが2つ残るのを避けるため。

### 3. テーブルは今リリースでは落とさない

`AttendReport` / `AttendEntry` のクラス定義だけ非推奨の注記付きで残し、
`DeleteModel` マイグレーションは次のリリースに回す（CLAUDE.md 絶対ルール7の
expand/contract）。画面を消した状態を先に本番へ出し、既存レコードが本当に
不要だと確認できてからテーブルを落とす。戻す場合は revert で足りる。

CI が `makemigrations --check` を回しているため、モデルを消さずに残すことは
「マイグレーション差分なし」と両立する。

## 影響

- 削除: `apps/attendance` の8ビュー・8URL・`AttendReportForm` /
  `AttendEntryForm` / `AttendEntryFormSet`・`utils.py`・admin 登録2件と inline
- 削除: `templates/attendance/` の6枚（report_list / report_form /
  report_detail / entry_list / employee_record / summary）
- 削除: `workers.services.get_attendance_summary()`（未使用の重複）
- 変更: サイドバーの「勤怠」グループは 出社予定・月次サマリ・勤怠設定 の3項目。
  月次サマリは `reports:monthly_summary` を指す
- 変更: `/attendance/` は `/attendance/plans/` へリダイレクト
- 残置: `AttendReport` / `AttendEntry` のモデル定義とテーブル（次リリースで削除）
- テストへの影響なし（`tests/test_attendance_plans.py` は出社予定のみを対象）

## 積み残し

`AttendEntry` は `break_minutes`（休憩）と `early_minutes`（早出）を持っていたが、
`DailyReport` 側は休憩を「8時間超なら一律60分」と `calculate_hours()` に
ハードコードしており、早出の概念がない。早出手当を実務で扱うなら、日報側に
項目を足す必要がある。本 ADR の範囲外とし、別途判断する。
