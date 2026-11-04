# Review Insights + Architecture Fixes Integration Plan

> **For agentic workers:** Use superpowers:executing-plans to execute the authorized integration in this session. Track each step below.

**Goal:** Integrate Stage 1 Review Insights and Architecture Fixes on one isolated branch, then run all automated suites.

**Architecture:** Start from `feature/architecture-fixes` (`59d7470`) and merge `feature/review-insights` (`1774030`), whose common ancestor is `eaa8477`. Preserve both sets of behavior; resolve documentation conflicts by purpose. No new product features or dependency changes.

**Tech Stack:** FastAPI / SQLAlchemy 2 / React 18 / TypeScript / Vite / pytest / Playwright.

**Spec:** User handoff request dated 2026-11-03 in the Codex conversation; repository `AGENTS.md`.

## Global Constraints

- Work only in `/home/user/projects/Jobseeker-integration`, branch `feature/integration-review-architecture`.
- Preserve original branches and all original-directory uncommitted launcher/doc work, including D-28.
- Never read/copy `.env`, development DB, or user recordings. No real Supabase/OpenAI calls.
- No push, PR creation, main merge, Stage 2, or gaze Phase 1.
- Keep API/schema contracts and dependency versions; change code only for proven integration defects.
- A merge commit is authorized by the requested merge; do not create unrelated commits.

## Review Focus

- Recording revocation and orphan cleanup must stay within fresh test-only DB/storage.
- E2E must start its own servers and never reuse a developer backend.
- Recorded-answer Review Insights tests and card contrast fixes must survive the merge.
- Unit tests must stay under `web/tests/unit/`; browser counts must exclude them.
- Treat the known gaze-lab timing failure separately from integration regressions.

### Task 1: Verify baseline and recording isolation

**Files:** Read `web/playwright.config.ts`, `web/e2e/env.ts`, `backend/tests/conftest.py`, `backend/app/retention.py`, and test specs. Test artifacts only in temporary or ignored integration-worktree paths.

**Interfaces:** Input: source branch tips and original-work checksum snapshot. Output: validated isolated environment.

- [x] Check Git history, worktrees, unique commits, dirty files, and visible processes.
- [x] Snapshot hashes of original uncommitted files; create the requested worktree from Architecture Fixes.
- [x] Run Architecture baseline pytest, build, and unit tests; record actual output.
- [x] Verify fresh canonical temporary recording path, fresh SQLite DB, disabled external services, screenshot opt-in, and `reuseExistingServer: false` before E2E.

### Task 2: Merge both branches

**Files:** Expected conflict `docs/progress.md`; automatic merges include `web/e2e/review-insights.spec.ts`. Preserve new `web/e2e/review-insights-recorded.spec.ts` and contrast CSS.

**Interfaces:** Input: validated branch tips. Output: conflict-free merge tree with both histories preserved.

- [x] Run `git merge --no-ff --no-commit feature/review-insights`.
- [x] Resolve conflicts semantically: current unit paths/Architecture safety changes plus Stage 1 recorded-answer evidence and known gaze issue.
- [x] Check unmerged paths, whitespace, and preservation of each requested change.

### Task 3: Validate, document, and finish locally

**Files:** Update `docs/progress.md`; append integration decision in `docs/decisions.md` without importing another session's D-28; update this checklist. Production code only if a reproduced integration defect requires it.

**Interfaces:** Input: merged tree. Output: tested local merge commit, exact evidence, and PR follow-up guidance.

- [x] Run full backend pytest, frontend build, and frontend unit suite.
- [x] Check Chromium shared libraries and port availability, then run all desktop/mobile Playwright tests with a fresh temporary recording directory.
- [x] Diagnose failures; rerun only as evidence warrants. Do not increase timeouts or remove features to obtain green tests.
- [x] Record separate unit/browser counts, skips/failures, external-service limitations, and Stage 2 readiness.
- [x] Review merge diff and source-feature preservation; verify original-work hashes and branch refs unchanged.
- [x] Create the local merge commit, verify both parents/ancestors and final clean tracked state. Do not push or create a PR.

## Execution evidence

- Architecture baseline: pytest **281 passed in 32.67s**; build exit 0; unit **68 passed (18.3s)**.
- Integrated tree: pytest **281 passed in 34.01s**; build exit 0 (Vite **5.08s**); unit **68 passed (16.2s)**.
- Full browser suite: **44 passed, 12 skipped (3.1m)**; desktop 28 passed, mobile 16 passed / 12 intentionally skipped; no failures or retries. Known gaze-lab failure did not reproduce.
- Independent read-only review found no integration defects. Real Supabase/OpenAI, real webcam/microphone behavior, Stage 2 and gaze Phase 1 were outside this run.
- Original-work preservation: 9 file hashes, original Git status, and every preexisting local/remote-tracking ref checked unchanged. No document screenshot changes.
- No production bugfix or dependency/schema/API change was needed beyond the requested merge. Local merge commit only; keep branch/worktree for user review and later PR.
