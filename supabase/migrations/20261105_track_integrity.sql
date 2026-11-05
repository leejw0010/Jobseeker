-- Additive Track integrity upgrade. Preserve old current states and submitted flags.
-- No legacy manual intent or actual submission is inferred. Run before this app release.
create table if not exists application_states (
 application_id uuid primary key references applications(id) on delete cascade,
 baseline_stage text check (baseline_stage in ('서류','인적성','1차면접','2차면접','최종')),
 baseline_status text check (baseline_status in ('진행중','합격','불합격','보류')),
 override_stage text check (override_stage in ('서류','인적성','1차면접','2차면접','최종')),
 override_status text check (override_status in ('진행중','합격','불합격','보류')),
 override_origin text check (override_origin in ('manual','legacy')),
 revision integer not null default 0 check (revision >= 0),
 check ((baseline_stage is null) = (baseline_status is null)),
 check ((override_origin is null and override_stage is null and override_status is null
          and baseline_stage is not null) or
        (override_origin is not null and override_stage is not null and override_status is not null))
);
create table if not exists essay_submissions (
 id uuid primary key default gen_random_uuid(),
 essay_item_id uuid not null references essay_items(id) on delete cascade,
 version_id uuid not null references answer_versions(id) on delete cascade,
 sequence integer not null check (sequence > 0),
 confirmed_at timestamptz not null default now(),
 source text not null check (source in ('web','extension')),
 unique(essay_item_id,sequence)
);
alter table application_states enable row level security;
alter table essay_submissions enable row level security;
drop policy if exists application_states_own on application_states;
create policy application_states_own on application_states for all
 using (exists(select 1 from applications a where a.id=application_id and a.user_id=auth.uid()))
 with check (exists(select 1 from applications a where a.id=application_id and a.user_id=auth.uid()));
drop policy if exists essay_submissions_read on essay_submissions;
create policy essay_submissions_read on essay_submissions for select
 using (exists(select 1 from essay_items e join applications a on a.id=e.application_id
   where e.id=essay_submissions.essay_item_id and a.user_id=auth.uid()));
drop policy if exists essay_submissions_insert on essay_submissions;
create policy essay_submissions_insert on essay_submissions for insert
 with check (exists(select 1 from essay_items e join applications a on a.id=e.application_id
   join answer_versions v on v.essay_item_id=e.id
   where e.id=essay_submissions.essay_item_id and v.id=essay_submissions.version_id and v.is_submitted and a.user_id=auth.uid()));
-- No UPDATE/DELETE policy: confirmed history is append-only. Parent deletion still cascades.
