# Setup

This profile README project generates a language-stat SVG from all repositories visible to your GitHub token.

It does not use third-party stat cards. The SVG is generated inside GitHub Actions and committed into `assets/languages.svg`.

## Files

- `README.md` — profile README.
- `assets/languages.svg` — generated language card shown in README.
- `scripts/update_language_stats.py` — GitHub API collector and SVG renderer.
- `.github/workflows/update-language-stats.yml` — workflow that updates the card.

## Create the profile repository

1. Create a new GitHub repository.
2. The repository name must be exactly the same as your GitHub username.
3. Make the repository public.
4. Upload all files from this project into the repository root.

GitHub shows a profile README only when a public repository has the same name as the account username and contains `README.md` in the root.

## Create token

Create a Personal Access Token that can read the repositories you want to include.

Recommended:

- Fine-grained token
- Repository access: all repositories you want to count
- Repository permissions: Metadata read

If fine-grained access is annoying for private repositories, use a classic token with `repo` scope.

Do not rely on the default `GITHUB_TOKEN` for this. It is meant for the repository where the workflow runs, so it will not collect all private repositories across your account.

## Add secret

Repository → Settings → Secrets and variables → Actions → New repository secret

Name:

`GH_STATS_TOKEN`

Value:

paste the token

## Run

Repository → Actions → Update language stats → Run workflow

After the first successful run, the workflow commits a new `assets/languages.svg`. The README will show real percentages from your repositories.

## Useful settings

Edit `.github/workflows/update-language-stats.yml`:

- `REPO_AFFILIATION: owner,collaborator,organization_member` — count owned repos, collaborator repos, and organization repos visible to the token.
- `INCLUDE_PRIVATE: "true"` — include private repos visible to the token.
- `INCLUDE_FORKS: "false"` — keep forks out so foreign code does not ruin the stats.
- `INCLUDE_ARCHIVED: "true"` — include archived repos.
- `EXCLUDE_CURRENT_REPO: "true"` — do not count this profile repository itself.
- `MAX_LANGUAGES: "8"` — number of languages shown on the card.

## Privacy note

The generated SVG does not contain private repository names. It only shows aggregated language percentages, total code size, and repository counts.
