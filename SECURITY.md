# Security Policy

## Reporting

Do **not** open a public GitHub issue for anything sensitive. If you find a
problem that could expose a secret (an API key, a session cookie, credentials),
report it privately to the repository owner instead.

## Secrets

This project reads all credentials from environment variables (or a local `.env`
file that is git-ignored). No secret value is ever committed to the repository.

- `.env` is in `.gitignore`; only `.env.example` (placeholders, no real values)
  is tracked.
- Browser profiles, cached cookies, and scraper state (`.cache/`,
  `browser_state.json`, profile/storage-state files) are git-ignored — they can
  hold session tokens and must never be committed.
- In CI, secrets are provided through GitHub Actions secrets
  (`${{ secrets.* }}`) and are never printed to logs.

## If a secret is exposed

1. Revoke / rotate the key at the provider immediately
   (e.g. Firecrawl API key, any COMC session cookie).
2. Replace it in your local `.env` and in the GitHub Actions secret.
3. Note that anything committed to git history stays in history until the history
   is rewritten — rotation is the reliable fix.
