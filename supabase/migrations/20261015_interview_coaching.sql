-- Existing Supabase projects: run this after the original schema.sql.
-- New tables only; existing applications, answers and recordings are retained.
create table if not exists practice_private_questions (
  question_id uuid primary key references questions(id) on delete cascade
);

create table if not exists practice_contexts (
  session_id uuid primary key references practice_sessions(id) on delete cascade,
  snapshot json not null,
  followups_enabled boolean not null default false
);

create table if not exists answer_coaching (
  answer_id uuid primary key references practice_answers(id) on delete cascade,
  parent_answer_id uuid unique references practice_answers(id) on delete set null,
  followup_reason text,
  report json
);

alter table practice_contexts enable row level security;
alter table answer_coaching enable row level security;
alter table practice_private_questions enable row level security;

drop policy if exists ppq_own on practice_private_questions;
create policy ppq_own on practice_private_questions for all
  using (exists (select 1 from questions q where q.id = question_id and q.user_id = auth.uid()))
  with check (exists (select 1 from questions q where q.id = question_id and q.user_id = auth.uid()));

drop policy if exists pc_own on practice_contexts;
create policy pc_own on practice_contexts for all
  using (exists (select 1 from practice_sessions s where s.id = session_id and s.user_id = auth.uid()))
  with check (exists (select 1 from practice_sessions s where s.id = session_id and s.user_id = auth.uid()));

drop policy if exists ac_own on answer_coaching;
create policy ac_own on answer_coaching for all
  using (exists (select 1 from practice_answers a join practice_sessions s on s.id = a.session_id
                where a.id = answer_id and s.user_id = auth.uid()))
  with check (
    exists (select 1 from practice_answers a join practice_sessions s on s.id = a.session_id
            where a.id = answer_id and s.user_id = auth.uid())
    and (parent_answer_id is null or exists (
      select 1 from practice_answers p join practice_sessions s on s.id = p.session_id
      join practice_answers child on child.session_id = p.session_id
      where p.id = parent_answer_id and child.id = answer_id and s.user_id = auth.uid()
    ))
  );
