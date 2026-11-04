# Main Integration and Release Validation Plan

**Goal:** Review PR #3, publish one integrated follow-up PR, merge both with original commit history preserved, and validate the final remote main.

**Baseline:** integration `519505b`; PR #3 head `95ad7c4`; remote main `7db4f5b`, verified 2026-11-04. User authorizes normal commits/push/PR/merge; no force push, history rewriting, policy bypass, operating DB changes, Stage 2 or gaze Phase 1.

## Protected state

- Preserve original launcher work: Start-JobSeeker.cmd, scripts/, decisions D-28 and progress changes; original9 file hashes saved under /tmp/jobseeker-main-integration-2026-11-04-original.json.
- Never read/copy private .env files, development DB or user recordings.
- Use existing isolated integration worktree and a fresh /tmp detached checkout for PR #3 (old config ignores RECORDINGS_DIR).
- External service keys blank; SQLite and recording fixtures temporary; document screenshots opt-in only.

## Steps

- [x] Inspect local/remote tips, worktrees, PR #3 and reviews; preserve integration baseline with backup/integration-before-main-2026-11-04.
- [x] Verify write capability: Git CLI lacks credentials; GitHub backup-ref request rejected403 Resource not accessible by integration. No remote ref was created.
- [x] Independently review PR #3 and integrated code. Reproduce defects before fixing.
- [x] Fix stale retention deletion and user-clear cutoff with conditional path updates and temporary-data regression matrix.
- [x] Fix camera ownership while detector/permission startup is pending; retain readiness/metric semantics.
- [x] Correct false-positive Track retry and extension session/sync tests; verify deliberate mutations fail in throwaway copies.
- [x] Validate exact PR #3 head in isolated checkout: pytest136 passed, build passed, desktop/mobile E2E10 passed. No unit script exists at this head.
- [x] Validate final integrated tree: full pytest, build, unit, all desktop/mobile E2E; check GazeLab excluded from production artifacts.
- [x] Complete a fresh independent review of fixes and record final results/limitations in progress/decisions.
- [x] Commit reviewed local changes and prepare complete integration PR title/body.
- [ ] Push integrated branch once credentials are available; keep original branches and commit SHAs.
- [ ] Merge PR #3 with expected head95ad7c4 only when final integrated publication is ready and required policies are satisfied.
- [ ] Create one follow-up PR main <- feature/integration-review-architecture; validate actual diff and merge with expected tested SHA.
- [ ] Fetch final remote main into an isolated worktree, run all suites and report actual remote commit/PR states.

## Known authentication blocker

Current GitHub connection reports pull:true/push:false. An actual refs creation request returned403. Git push dry-run returned128, could not read Username, terminal prompts disabled. Branch protection read also returned403; no policy assumptions or bypasses are allowed. Complete all safe local work before reporting only this required access change. Do not claim local integrated tests are post-merge remote-main tests.

## Validation evidence

- Exact PR #3 head95ad7c4: pytest136 passed in13.00s; build passed2.25s; desktop/mobile E2E10 passed48.2s.
- Final integrated tree: pytest290 passed62.91s; build passed4.38s; unit68 passed12.7s; full E2E47 passed/15 intentionally skipped3.8m (desktop31, mobile16+15skip), no unexpected/flaky results.
- Production artifacts contain no GazeLab route or lab UI. Runtime npm audit has2 existing moderate router advisories (high0/critical0); major dependency migration deferred, documented explicitly.
- Regression evidence: retention old-snapshot failures and missing/stale storage timestamp failures reproduced before fixes; camera startup lifecycle3 failures reproduced before fix. Corrected Track/extension tests reject deliberate faulty /tmp product copies that the former tests accepted.
- Source review feedback fully addressed without API/schema/dependency changes. Original launcher files/D-28 remain outside this branch. Remote operations remain blocked by actual authentication/permission errors, not missing task authorization.
