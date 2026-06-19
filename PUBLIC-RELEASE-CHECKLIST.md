# Public-release checklist (operator-only steps)

This repo is being made public so it can use free GitHub Actions minutes. The goal
is **low casual discovery**, not real security. The code is still findable by
anyone who searches GitHub's code index — the README scrub is cosmetic. Do the
manual steps below **before** flipping the repo public.

> Reality check: once the repo is public, **Actions logs and uploaded artifacts
> are world-downloadable**. If you want a scan's deal data to stay private, run the
> scan **locally** (`--fetch-mode playwright`) instead of via the `COMC Scan`
> workflow. The workflow here is hardened (no public issues, only a row *count* in
> the public run log, short artifact retention) but artifacts are still public.

## 1. Repo settings (GitHub web UI → Settings)

- [ ] **Rename** the repository to a neutral name (e.g. `price-compare`).
- [ ] Clear the **Description** field (remove any arbitrage/Pokemon/TCG wording).
- [ ] Clear all **Topics / tags**.
- [ ] **Features:** disable **Issues**, **Wiki**, **Discussions**, **Projects**,
      and **Sponsorships**.
- [ ] **Pages:** set Source to **None**.
- [ ] (Optional) Disable **Releases** packages/social-preview image if any reveal the use case.

## 2. Flip to public

- [ ] Settings → **General → Danger Zone → Change visibility → Public**.
      (Claude never does this — operator-only, irreversible-ish.)

## 3. Validate free Actions after going public

- [ ] Open **Actions** tab; confirm the `tests` workflow runs green on `ubuntu-latest`
      (it needs no secrets and no browser).
- [ ] Confirm `COMC Scan` only runs on **manual dispatch** (no cron is enabled) and
      that `FIRECRAWL_API_KEY` is set as a repo **Actions secret** before dispatching.

## 4. Delete stale remote branches (operator runs these)

Both branches below contain only the delivery work already merged into `main` via
PRs #2 and #3 (different hashes after squash-merge), so deleting them loses nothing:

```bash
git push origin --delete claude/self-evolving-agent-integration-budf77
git push origin --delete docs/canonical-delivery-format
```

(Claude does not delete remote branches. After this PR merges, also delete
`chore/prepare-public-release`.)

## 5. After merge — secret hygiene

- [ ] Confirm no real secret is in git history (this PR's audit found none).
- [ ] If you ever committed a `.env`, a session cookie, or a browser profile:
      rotate the Firecrawl API key and the COMC session cookie, since rotation —
      not a README edit — is what actually protects them.
