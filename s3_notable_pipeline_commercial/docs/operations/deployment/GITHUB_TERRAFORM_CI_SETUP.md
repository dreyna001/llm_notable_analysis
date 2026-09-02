# GitHub Terraform CI Setup

Use this once to make Terraform checks mandatory before changes reach `main`.
You need repository administrator access. No AWS credentials or repository
secrets are required because this workflow never plans, applies, or contacts a
customer account.

## 1. Push this feature branch

```bash
git switch codex/customer-deployment-readiness
git push -u origin codex/customer-deployment-readiness
```

## 2. Enable GitHub Actions

1. Open the repository on GitHub.
2. Go to **Settings → Actions → General**.
3. Under **Actions permissions**, allow GitHub Actions to run.
4. If actions are restricted, allow these sources:
   - `actions/checkout@*`
   - `actions/setup-python@*`
   - `hashicorp/setup-terraform@*`
5. Under **Workflow permissions**, select read-only repository permissions.
6. Save.

Reference: [GitHub Actions repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).

## 3. Open the first pull request

1. Create a pull request from `codex/customer-deployment-readiness` into `main`.
2. Wait for the status check named `terraform`.
3. Open its log if it fails. Do not merge until it passes.

The check runs Terraform formatting, initialization without the customer
backend, validation, focused tests, and Checkov. It cannot deploy infrastructure.

## 4. Protect `main`

After the first `terraform` check appears:

1. Go to **Settings → Rules → Rulesets**.
2. Select **New ruleset → New branch ruleset**.
3. Name it `main pull request checks`.
4. Set **Enforcement status** to **Active**.
5. Target the default branch (`main`).
6. Enable **Require a pull request before merging**.
7. Require at least one approval.
8. Enable **Require status checks to pass**.
9. Add the required check `terraform`, with GitHub Actions as its source.
10. Enable **Require branches to be up to date before merging**.
11. Enable **Restrict deletions** and **Block force pushes**.
12. Do not add bypass users unless your organization requires them.
13. Create the ruleset.

Reference: [GitHub repository rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository).

## 5. Confirm it works

The pull request must show `terraform` as passed before GitHub allows the merge.
If the check is missing, confirm Actions are enabled and that the required check
name is exactly `terraform`.

## Next

Merge only after the review and `terraform` check both pass.
