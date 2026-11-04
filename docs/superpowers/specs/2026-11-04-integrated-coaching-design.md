# Stage 2 and integrated interview coaching

This implements the user's Stage 2 + Multimodal Interview Coaching request on `de86b80`. Existing categories, three coaching criteria, Review Insights, automatic debrief, recording policies, and Track contracts remain compatible.

## Decisions

Use the existing FastAPI/SQLAlchemy and React stack, without new heavy models or UI dependencies. Add a versioned taxonomy, relational question tags and immutable per-answer classification snapshots. Preserve legacy null snapshots, including redrills; never infer past tags from current questions. Public-bank backfill must match exact original text/category/job and only untouched public bank questions.

New PostgreSQL columns must not break installations awaiting manual migration. `PRACTICE_INSIGHTS_ENABLED=false` is the default and omits new ORM mappings entirely. When enabled, require the new schema before serving requests; SQLite alone may upgrade automatically. Expose runtime taxonomy capability so the frontend can hide unavailable classification controls. Production migration is manual and additive. During flag-off rollback an explicit text replacement checks schema metadata and clears an already-present optional recording signature with typed SQL; an unmigrated schema receives no optional-column UPDATE or DDL. Existing STT status keeps its original meaning.

Derived audio/video measurements remain in tab memory, are optional, bind to a successful recording revision and disappear on refresh. They are never sent to the backend or external AI. No frames, landmarks or raw feature arrays are stored. Browser energy-based speech candidates must be labelled as candidates, with insufficient/constant/clipped/gapped signals unavailable; do not call them verified speech. Keep the whole-recording pace separate from candidate-active pace. Transcript filler occurrences are textual candidates, without acoustic timestamps. Reuse the existing microphone analyser and camera sampling; measurement failure cannot prevent saving.

Only recordings receive delivery reports. Typed answers, failed uploads and stale recording revisions must not receive them. Transcript edits invalidate derived interpretation and session debrief input fingerprints. A minimal recording-revision/text signature persists with the new schema, so R1 and per-answer speed also remain invalid after refresh. Old unverified records have no speed evaluation. First manual transcription is user confirmation, not acoustic verification. Legacy debriefs without input fingerprints remain readable as clearly marked historical originals and never feed current integrated conclusions. Coaching evidence uses actual substring quotes and snapshot hashes; invalid optional AI extensions cannot invalidate the existing core coaching. All new evidence metadata is server-owned.

Extend the existing debrief presentation with a grounded local integrated coaching narrative, item comments and prioritised next actions. Reuse existing text-only AI debrief; do not send private delivery metrics to it. Improved-answer examples use verbatim transcript material and explicit missing-information prompts, never invented achievements. Extra automatic LLM calls: zero. Classification metadata is requested within existing generation/coaching calls only when enabled.

G1/G2 remain confined to the experimental lab, disabled in real interview assessment. Reuse existing diagnostics and add rejected-frame/quality reporting and a reproducible three-run real-webcam protocol. No threshold tuning or claims of improved real accuracy without human measurements.

## Alternatives considered

Persisting delivery metrics in PostgreSQL would support reopening reviews but expands the privacy/storage contract; defer it. Sending aggregates to AI could produce a more flexible multimodal narrative but changes external data scope; use local evidence-driven composition instead. Replacing the existing coaching/debrief would duplicate behaviour; extend it.

## Acceptance

Taxonomy/filtering/snapshots work across ordinary sessions, followups and redrills, preserve ownership and legacy inputs, and tolerate disabled/unmigrated deployments. Desktop/mobile review exposes counts and grounded comments via accessible text and links. Pure boundary tests cover silence/gaps/malformed metrics/stale reports; backend tests cover migration, validation, ownership, concurrency and evidence/debrief invalidation. Full pytest/build/unit/E2E must pass with isolated temporary DB/recordings and no external services. Hardware, actual Supabase/RLS and real model quality remain explicitly unverified until separately tested.
