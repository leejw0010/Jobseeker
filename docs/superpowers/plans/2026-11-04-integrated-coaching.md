# Integrated Coaching Implementation Plan

> **For agentic workers:** Use Superpowers implementation, TDD, independent review and verification skills. The user explicitly authorised autonomous execution and independent parallel work; no design confirmation pause is needed.

**Goal:** Add question classification and grounded multimodal review without changing existing contracts or weakening privacy.

**Architecture:** Extend the existing question/session/coaching flow. Keep delivery summaries in browser memory. Gate new schema mappings until a manual PostgreSQL migration is applied.

**Tech Stack:** Existing FastAPI, SQLAlchemy, React, TypeScript, Playwright; no new heavy dependencies.

**Spec:** `docs/superpowers/specs/2026-11-04-integrated-coaching-design.md`, and the user's attached detailed request.

## Global Constraints

- Work only in `/tmp/Jobseeker-coaching`, branch `codex/stage2-multimodal-coaching`; preserve all prior worktrees and dirty launcher files.
- Never read .env, existing recordings or real development databases; never use production Supabase or paid AI in tests.
- Preserve old API names/semantics, category values and three coaching criteria. New fields are optional.
- Recording consent/retention/deletion stays unchanged. No delivery data, images or landmarks leave the browser.
- No G1/G2 production assessment, force push, history rewriting or automatic production migration.
- Agents own disjoint files; root owns integration, docs, final verification and GitHub. Agents do not commit or spawn agents.

## Review Focus

- Disabled schema must run legacy SQL even against an unmigrated PostgreSQL schema.
- Changing tags/transcripts or replacing recordings must not make old interpretations look current.
- Empty, silent, invalid, gapped or text-only answers must not acquire made-up measurements.
- Invalid optional AI metadata must not reject valid core coaching or trigger extra retries.
- Followup visibility, ownership, filtered selection and redrill legacy null preservation must survive classification.

### Task 1: Backend classification and coaching contracts

Owner: backend agent. Files: `backend/` and new migration/full schema under `supabase/`. Do not edit web/docs.

Interfaces: `GET /practice/taxonomy` returns `{enabled, taxonomy_version, question_types:[{key,label,definition}], competencies:[{key,label,definition}], max_competencies:3}`. Questions add nullable `question_type`, `taxonomy_version`, `tagging_source` and `competency_keys: string[]`. Answer adds nullable `question_classification` snapshot. Question create/edit classification uses `question_type` and `competency_keys`; `PUT /practice/questions/{id}/classification`. GET repeated `question_type`, repeated `competency_key`, `competency_match=any|all`. Session input uses `question_types`, `competency_keys`, `competency_match`; explicit IDs retain priority. Generation input optional `question_type`, `competency_keys`. Session summaries add `competency_keys`, `classification_missing_count`.

- [ ] Write failing backend tests for invalid/duplicate/>3 keys, ownership/filter combinations, snapshot immutability, all creation paths and legacy null.
- [ ] Implement taxonomy and atomic classification/filter/snapshot service, exact public bank mappings and additive migration with RLS and UUIDs.
- [ ] Test flag-off unmigrated SQL and flag-on SQLite upgrade/startup schema validation. Default schema flag is false; conftest/E2E explicitly enable it.
- [ ] Extend existing coaching call with optional validated `competency_evidence`, disabled by default; hash transcript and snapshot; isolate optional errors. Existing three criteria unchanged.
- [ ] Add complete debrief input fingerprinting and suppress stale narrative, including edit during background processing.
- [ ] Run full backend pytest and report commands/results, no external calls.

### Task 2: Browser delivery measurements and gaze diagnostics

Owner: media agent. Files: existing recorder/face hooks, `web/src/video/`, `web/src/gaze/`, GazeLab, new `web/src/delivery/`, corresponding unit tests, `docs/research/2026-11-04-gaze-protocol.md`. Do not edit SessionRunner/Review/types/api or other docs.

Interfaces: export `DeliverySummary` and `summarizeVoice` from `web/src/delivery/voice.ts`. Recorder stop adds optional `delivery` alongside unchanged `{blob,durationSec}`. Voice units are seconds; include method/quality, total/active candidate seconds, pauses and coverage with explicit limitations. Extend video memory store optional revision key on `saveVideoSegment`/`getVideoSegments` preserving old signatures; report revision-aware access and clearing. Export similar voice memory storage helpers keyed session/answer/recorded_at.

- [ ] Write failing pure tests for silence/constant/nonfinite/gaps/partial coverage, pauses, filler text candidates and stale replacement revisions.
- [ ] Reuse analyser samples with bounded storage and adaptive energy candidate segmentation; never present RMS detection as verified speech. Failure returns unavailable and preserves recorder operation.
- [ ] Add derived video positioning/coverage comments without raw storage, and ensure summaries remain finite.
- [ ] Extend existing lab diagnostics for invalid/blink/pose/resolution/geometry reasons and document three-run protocol. Keep models experimental.
- [ ] Run web unit tests and report; coordinate any interface adjustments with root.

### Task 3: Classification UI and integrated feedback

Owner: frontend agent. Files: `web/src/types.ts`, `api.ts`, PracticeHome/SessionRunner/SessionReview/SessionList, new components/review modules and associated unit/E2E tests. Do not edit media hooks/video/gaze/delivery or backend/config/docs.

Interfaces: consume Task 1 runtime taxonomy contracts; use optional Task 2 recorder summary only after successful audio upload. Delivery stores bind to recorded_at; typed responses never save them. Local feedback combines current core coaching, snapshot evidence and available delivery summaries; no backend/LLM metric payload. Keep R1 insights and debrief, enhance their presentation.

- [ ] Write failing tests for coverage counts, null snapshots, no evidence/no data, priorities, stale reports, text-only and accessible browser flows.
- [ ] Add taxonomy editing/filtering/generation preferences and frozen chips; expose SessionList filtering.
- [ ] Add competencies panel, grounded item/per-answer comments and coherent session coaching narrative (~1min, shorter with few facts), with answer links and 2–3 next actions. Use existing debrief rather than duplicate summary request.
- [ ] Add optional grounded improved-answer outline with verbatim transcript and placeholders; no invented experience/numbers or automatic LLM call.
- [ ] Gate camera segment recording to audio mode, save metrics only after successful upload, invalidate replaced/stale reports; support disabling live hints.
- [ ] Run build/unit/targeted E2E and report.

### Task 4: Integration, independent review and release

Owner: root. Files: documentation, Playwright config and integration fixes after owner handoff.

- [ ] Establish baseline pytest/unit in isolated new worktree and record protected-file hashes.
- [ ] Reconcile actual contracts and add required browser tests; explicitly enable schema flag in temporary E2E backend.
- [ ] Run full backend pytest, frontend build, unit and desktop/mobile E2E, then request independent review of the full diff.
- [ ] Fix real defects with regression tests; rerun affected and required suites. Update README API table, decisions/progress and manual migration/rollback procedure.
- [ ] Check no secrets/data artifacts staged; commit explicit file lists, push branch, create one PR with exact results/limits.
- [ ] Merge only if required checks, independent review, compatibility and data-protection conditions pass; use merge commit, preserve source branches. Verify final main in isolated validation checkout and report exact SHA/results/remaining hardware checks.
