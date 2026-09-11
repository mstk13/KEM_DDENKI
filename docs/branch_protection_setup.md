# main ブランチ保護の設定（リポジトリ管理者のみ）

「PM が OK を出すまで `main` にマージできない」状態を**仕組みとして**強制するための設定です。

> [!IMPORTANT]
> この設定にはリポジトリの **Admin 権限** が必要です。
> 現在 Admin を持つのは **@mstk13** のみです。他のメンバーは変更できません。
> 設定するまでは、ルールは「お願い」であって強制されません（誰でも `main` に直接 push できます）。

> [!WARNING]
> **2026-08-20 時点で、この設定は現在のプランでは使えません。**
> ブランチ保護も ruleset も **private リポジトリでは有料プラン限定**で、
> API を叩くと `403 Upgrade to GitHub Pro or make this repository public` が返ります。
>
> 使えるようにするには次のいずれかが必要です。
>
> - GitHub Pro 等の有料プランにする
> - リポジトリを public にする（業務データを含む構成なので現実的ではない）
>
> それまでは、`main` への直接 push を禁じるルールは**お願いベースのまま**です。
> なお `developer` が消える問題は保護ではなく手順で回避しています
> （[git_workflow.md](git_workflow.md#main-へのマージ) のリリースブランチ）。

---

## 設定手順（画面から・5分）

1. https://github.com/mstk13/KEM_DDENKI/settings/branches を開く
2. **Add branch protection rule** をクリック
3. **Branch name pattern** に `main` と入力
4. 下の表のとおりチェックを入れる
5. **Create** をクリック

| 設定項目 | チェック | 理由 |
|---------|:-------:|------|
| Require a pull request before merging | ✅ | `main` への直接 push を禁止する。これが本丸 |
| └ Require approvals（1人） | ✅ | PM の Approve なしにマージできなくなる |
| └ Dismiss stale approvals when new commits are pushed | ✅ | Approve 後に中身を差し替える抜け道を塞ぐ |
| └ Require review from Code Owners | ✅ | `.github/CODEOWNERS` の @mstk13 のレビューを必須にする |
| Require status checks to pass before merging | ✅ | CI が赤いままマージできなくなる |
| └ Require branches to be up to date before merging | ✅ | 古い `developer` のままマージするのを防ぐ |
| └ Status checks: `test` | ✅ | `.github/workflows/ci-saas.yml` のジョブ名 |
| Do not allow bypassing the above settings | ✅ | 管理者自身にもルールを適用する |
| Allow force pushes | ❌ | 履歴を壊せてしまう |
| Allow deletions | ❌ | `main` を消せてしまう |

`developer` ブランチには保護をかけません（開発者が自由に push できる必要があるため）。

---

## コマンドで設定する場合

`gh` に Admin 権限のアカウントでログインした状態で実行します。

```bash
gh api -X PUT repos/mstk13/KEM_DDENKI/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=test" \
  -F "enforce_admins=true" \
  -F "required_pull_request_reviews[required_approving_review_count]=1" \
  -F "required_pull_request_reviews[dismiss_stale_reviews]=true" \
  -F "required_pull_request_reviews[require_code_owner_reviews]=true" \
  -F "restrictions=null" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false"
```

---

## 設定できたかの確認

```bash
gh api repos/mstk13/KEM_DDENKI/branches/main/protection --jq '{
  pr_required: (.required_pull_request_reviews != null),
  approvals: .required_pull_request_reviews.required_approving_review_count,
  code_owners: .required_pull_request_reviews.require_code_owner_reviews,
  ci: .required_status_checks.contexts,
  admins_included: .enforce_admins.enabled
}'
```

期待する結果:

```json
{
  "pr_required": true,
  "approvals": 1,
  "code_owners": true,
  "ci": ["test"],
  "admins_included": true
}
```

実際に効いているかは、`main` に直接 push を試して弾かれることで確認できます。

```bash
git switch main && git commit --allow-empty -m "test" && git push origin main
# → ! [remote rejected] main -> main (protected branch hook declined)
git reset --hard origin/main   # 試したコミットを消す
```

---

## 開発メンバーを追加するとき

1. https://github.com/mstk13/KEM_DDENKI/settings/access で招待する（**Write** 権限）
2. Tailscale にその人の端末を追加する（開発環境・本番を見るのに必要）。
   端末に Tailscale を入れ、共有アカウント **kec.apps.network@gmail.com**（Google でログイン）で
   サインインしてもらう。パスワードは直接伝え、リポジトリには書かない（手順: [tailscale_setup.md](tailscale_setup.md)）
3. [開発者ガイド](developer_guide.md) を渡す

Admin 権限は渡さないでください。Write があれば `developer` への push と PR 作成はできます。
