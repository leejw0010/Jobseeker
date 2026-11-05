-- JobSeeker: Practice(②) + Track(③) 스키마
-- Supabase SQL Editor에 그대로 붙여 넣어 실행하면 됩니다.
-- 모든 사용자 데이터는 auth.users(id)에 묶이고, RLS로 본인 행만 접근 가능합니다.

create extension if not exists "pgcrypto";

-- ───────────────────────── ② Practice ─────────────────────────

-- 질문은행. user_id가 null이면 공용 질문, 값이 있으면 사용자 맞춤(생성) 질문
create table if not exists questions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users(id) on delete cascade,
  category      text not null check (category in ('인성','직무','기업','상황','인적성')),
  job_category  text,                       -- 예: 개발, 기획, 마케팅 (null = 공통)
  text          text not null,
  source        text not null default 'bank' check (source in ('bank','generated','custom')),
  application_id uuid,                      -- 맞춤 질문을 만든 근거 지원 건
  created_at    timestamptz not null default now()
);

-- 연습 세션(자유 연습 / 모의시험)
create table if not exists practice_sessions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  mode            text not null check (mode in ('free','mock')),
  title           text not null,
  application_id  uuid,
  prep_sec        int  not null default 30,  -- 모의시험: 답변 준비 시간
  answer_sec      int  not null default 90,  -- 모의시험: 답변 제한 시간
  created_at      timestamptz not null default now(),
  finished_at     timestamptz,
  -- 세션 종료 후 자동 디브리프 {lesson, next_action, moments[], generated_at, model}
  debrief         jsonb,
  debrief_status  text not null default 'none'
                  check (debrief_status in ('none','pending','done','failed','unavailable')),
  debrief_started_at   timestamptz,        -- 디브리프 작업(답변 점검 + 요약) 시작 시각. 끝나면 비운다(작업의 표시)
  debrief_heartbeat_at timestamptz,        -- 작업이 마지막으로 살아 있다고 알린 시각(5분 넘게 없으면 다시 시작)
  debrief_requested_at timestamptz         -- 작업 중에 들어온 종료·재생성 요청 시각(작업이 한 바퀴 더 돈다)
);

-- 세션 안의 개별 답변(녹음 → 전사 → 회고)
create table if not exists practice_answers (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid not null references practice_sessions(id) on delete cascade,
  question_id      uuid not null references questions(id) on delete cascade,
  order_no         int  not null,
  audio_path       text,                    -- Storage 버킷 'recordings' 내 경로(원본을 지우면 null)
  duration_sec     real,
  transcript       text,
  stt_status       text not null default 'none' check (stt_status in ('none','done','failed','unavailable')),
  self_rating      int check (self_rating between 1 and 5),
  reflection_note  text,
  ai_feedback      text,
  recorded_at      timestamptz,             -- 녹음한 시각("답했다"의 기준. 원본이 지워져도 남는다)
  audio_expires_at timestamptz,             -- 원본 녹음 자동 삭제 시각
  audio_deleted_at timestamptz,             -- 원본 녹음을 지운 시각
  created_at       timestamptz not null default now()
);
create index if not exists practice_answers_audio_expiry_idx
  on practice_answers(audio_expires_at) where audio_path is not null;

-- 녹음 동의·원본 보관 설정(행이 없으면 미동의)
create table if not exists user_settings (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  consented_at  timestamptz,                -- null = 녹음 미동의(또는 철회)
  keep_audio    boolean not null default false,  -- true면 전사 후에도 원본 보관(보관 기한 뒤 자동 삭제)
  sweep_audio_before timestamptz,           -- 전체 삭제·철회 때 못 지운, 답변이 가리키지 않는 파일: 이 시각 전 것을 다음 정리가 지운다
  audio_cleared_at timestamptz,             -- 원본 녹음을 모두 지운(전체 삭제·철회) 시각: 그 전에 시작해 전사 중이던 업로드도 지운 것으로 저장한다
  updated_at    timestamptz not null default now()
);

-- ───────────────────────── ③ Track ─────────────────────────

create table if not exists applications (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  company       text not null,
  position      text not null,
  job_category  text not null default '기타',
  url           text,
  applied_at    date,
  stage         text not null default '서류' check (stage in ('서류','인적성','1차면접','2차면접','최종')),
  status        text not null default '진행중' check (status in ('진행중','합격','불합격','보류')),
  notes         text,
  source        text not null default 'web' check (source in ('web','extension')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index if not exists applications_user_url_uq
  on applications(user_id, url) where url is not null;

-- 단계별 결과 이력(서류 합격 → 인적성 불합격 …)
create table if not exists stage_events (
  id              uuid primary key default gen_random_uuid(),
  application_id  uuid not null references applications(id) on delete cascade,
  stage           text not null check (stage in ('서류','인적성','1차면접','2차면접','최종')),
  result          text not null check (result in ('대기','합격','불합격')),
  event_date      date not null default current_date,
  memo            text,
  created_at      timestamptz not null default now()
);

-- 자소서 문항 단위
create table if not exists essay_items (
  id              uuid primary key default gen_random_uuid(),
  application_id  uuid not null references applications(id) on delete cascade,
  question_text   text not null,
  char_limit      int,
  created_at      timestamptz not null default now()
);

-- 문항별 답변 버전
create table if not exists answer_versions (
  id            uuid primary key default gen_random_uuid(),
  essay_item_id uuid not null references essay_items(id) on delete cascade,
  version_no    int  not null,
  content       text not null,
  char_count    int  not null,
  source        text not null default 'web' check (source in ('web','extension')),
  is_submitted  boolean not null default false,
  created_at    timestamptz not null default now(),
  unique (essay_item_id, version_no)
);

-- ───────────────────────── RLS ─────────────────────────
alter table questions          enable row level security;
alter table practice_sessions  enable row level security;
alter table practice_answers   enable row level security;
alter table applications       enable row level security;
alter table stage_events       enable row level security;
alter table essay_items        enable row level security;
alter table answer_versions    enable row level security;
alter table user_settings      enable row level security;

create policy q_read  on questions for select using (user_id is null or user_id = auth.uid());
create policy q_write on questions for all    using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy ps_all on practice_sessions for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy pa_all on practice_answers  for all using (
  exists (select 1 from practice_sessions s where s.id = session_id and s.user_id = auth.uid()));
create policy us_all on user_settings for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy app_all on applications for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy se_all  on stage_events for all using (
  exists (select 1 from applications a where a.id = application_id and a.user_id = auth.uid()));
create policy ei_all  on essay_items  for all using (
  exists (select 1 from applications a where a.id = application_id and a.user_id = auth.uid()));
create policy av_all  on answer_versions for all using (
  exists (select 1 from essay_items e join applications a on a.id = e.application_id
          where e.id = essay_item_id and a.user_id = auth.uid()));

-- 녹음 파일 버킷(비공개). 경로 규칙: {user_id}/{session_id}/{answer_id}.webm
insert into storage.buckets (id, name, public) values ('recordings','recordings', false)
  on conflict (id) do nothing;
create policy rec_own on storage.objects for all
  using (bucket_id = 'recordings' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = 'recordings' and (storage.foldername(name))[1] = auth.uid()::text);

-- 2026-10-15: 제출본 기반 면접 코칭
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


-- Manual additive migration; apply before enabling PRACTICE_INSIGHTS_ENABLED.
-- Existing answers intentionally retain NULL snapshots. Roll back by disabling the flag.
-- Safe to run again; no recordings, transcripts, coaching or user tags are changed.
alter table questions add column if not exists question_type text;
alter table questions add column if not exists taxonomy_version text;
alter table questions add column if not exists tagging_source text;
alter table practice_answers add column if not exists question_classification jsonb;
alter table practice_answers add column if not exists recording_transcript_sha256 varchar(64);

alter table questions drop constraint if exists questions_question_type_check;
alter table questions add constraint questions_question_type_check check
 (question_type is null or question_type in ('self_description','motivation','behavioral','situational','project_deep_dive','knowledge'));
alter table questions drop constraint if exists questions_tagging_source_check;
alter table questions add constraint questions_tagging_source_check check
 (tagging_source is null or tagging_source in ('curated','manual','ai','rule'));

create table if not exists question_competencies (
 question_id uuid not null references questions(id) on delete cascade,
 competency_key text not null check (competency_key in ('problem_solving','communication','collaboration','leadership','technical_expertise','adaptability','analytical_thinking')),
 position integer not null check (position between 0 and 2),
 primary key (question_id,competency_key)
);
create index if not exists question_competencies_key_idx on question_competencies(competency_key,question_id);
alter table question_competencies enable row level security;
drop policy if exists qc_read on question_competencies;
create policy qc_read on question_competencies for select using
 (exists(select 1 from questions q where q.id=question_id and (q.user_id is null or q.user_id=auth.uid())));
drop policy if exists qc_own on question_competencies;
create policy qc_own on question_competencies for all using
 (exists(select 1 from questions q where q.id=question_id and q.user_id=auth.uid()))
 with check (exists(select 1 from questions q where q.id=question_id and q.user_id=auth.uid()));

-- Exact original bank tuples only. Untagged public-bank rows with no application only.
with bank(category,job_category,question_text,question_type,competency_keys) as (values
 ('인성',null,'1분 동안 자기소개를 해 주세요.','self_description',array[]::text[]),
 ('인성',null,'본인의 장점과 단점을 하나씩 말씀해 주세요.','self_description',array[]::text[]),
 ('인성',null,'살면서 가장 몰입했던 경험은 무엇인가요?','behavioral',array[]::text[]),
 ('인성',null,'스트레스를 받을 때 어떻게 해소하나요?','self_description',array['adaptability']::text[]),
 ('인성',null,'가장 크게 실패했던 경험과 그 경험에서 배운 점을 말씀해 주세요.','behavioral',array['adaptability']::text[]),
 ('인성',null,'주변 사람들은 본인을 어떤 사람이라고 평가하나요?','self_description',array[]::text[]),
 ('상황',null,'팀 프로젝트에서 무임승차하는 팀원이 있다면 어떻게 하겠습니까?','situational',array['collaboration']::text[]),
 ('상황',null,'상사의 지시가 본인 생각과 다를 때 어떻게 하겠습니까?','situational',array['communication','collaboration']::text[]),
 ('상황',null,'마감 직전에 큰 오류를 발견했다면 어떻게 대처하겠습니까?','situational',array['problem_solving','analytical_thinking']::text[]),
 ('상황',null,'동시에 여러 업무가 몰렸을 때 우선순위를 어떻게 정하나요?','situational',array['analytical_thinking']::text[]),
 ('기업',null,'우리 회사에 지원한 동기는 무엇인가요?','motivation',array[]::text[]),
 ('기업',null,'입사 후 10년 뒤 본인의 모습을 말씀해 주세요.','motivation',array[]::text[]),
 ('기업',null,'다른 회사에도 지원했나요? 우리 회사가 1순위인 이유는 무엇인가요?','motivation',array[]::text[]),
 ('기업',null,'마지막으로 하고 싶은 말이 있나요?','self_description',array[]::text[]),
 ('직무','개발','가장 자신 있는 프로젝트를 소개하고, 본인이 맡은 기술적 역할을 설명해 주세요.','project_deep_dive',array['technical_expertise','problem_solving']::text[]),
 ('직무','개발','프로세스와 스레드의 차이를 설명해 주세요.','knowledge',array['technical_expertise']::text[]),
 ('직무','개발','REST API를 설계할 때 중요하게 생각하는 원칙은 무엇인가요?','knowledge',array['technical_expertise']::text[]),
 ('직무','개발','데이터베이스 인덱스는 언제 성능을 높이고, 언제 오히려 떨어뜨리나요?','knowledge',array['technical_expertise','analytical_thinking']::text[]),
 ('직무','개발','해결하기 어려웠던 버그를 어떻게 찾아 고쳤는지 말씀해 주세요.','behavioral',array['problem_solving','technical_expertise']::text[]),
 ('직무','개발','코드 리뷰에서 지적을 받았을 때 어떻게 대응하나요?','behavioral',array['communication','adaptability']::text[]),
 ('직무','기획','최근 인상 깊게 사용한 서비스와 그 이유를 말씀해 주세요.','knowledge',array['analytical_thinking']::text[]),
 ('직무','기획','서비스 지표가 갑자기 떨어졌다면 원인을 어떻게 분석하겠습니까?','situational',array['analytical_thinking','problem_solving']::text[]),
 ('직무','기획','개발자와 일정·범위를 두고 의견이 다를 때 어떻게 조율하나요?','situational',array['communication','collaboration']::text[]),
 ('직무','마케팅','최근 본 마케팅 캠페인 중 성공적이라고 생각한 사례를 분석해 주세요.','knowledge',array['analytical_thinking','technical_expertise']::text[]),
 ('직무','마케팅','한정된 예산으로 신규 고객을 늘려야 한다면 어떤 전략을 쓰겠습니까?','situational',array['problem_solving','technical_expertise']::text[]),
 ('직무','데이터','분석 결과가 직관과 다르게 나왔을 때 어떻게 검증하나요?','knowledge',array['analytical_thinking']::text[]),
 ('직무','데이터','A/B 테스트를 설계할 때 주의해야 할 점은 무엇인가요?','knowledge',array['analytical_thinking','technical_expertise']::text[]),
 ('인적성',null,'[언어] 다음 글의 핵심 주장을 한 문장으로 요약하는 연습: 최근 읽은 기사 하나를 30초 안에 요약해 보세요.','knowledge',array['communication']::text[]),
 ('인적성',null,'[수리] 정가의 20%를 할인한 뒤 다시 10%를 할인하면 정가 대비 총 몇 % 할인인가요? 풀이 과정을 말해 보세요.','knowledge',array['analytical_thinking']::text[]),
 ('인적성',null,'[추리] ''A는 B보다 크고, C는 A보다 작지만 B보다 크다''일 때 세 값의 순서를 말해 보세요.','knowledge',array['analytical_thinking']::text[])
), candidates as (
 select q.id,b.question_type,b.competency_keys from questions q join bank b
 on q.category=b.category and q.job_category is not distinct from b.job_category and q.text=b.question_text
 where q.user_id is null and q.source='bank' and q.application_id is null
 and q.question_type is null and q.taxonomy_version is null and q.tagging_source is null
 and not exists(select 1 from question_competencies qc where qc.question_id=q.id)
), updated as (
 update questions q set question_type=c.question_type,taxonomy_version='interview-v1',tagging_source='curated'
 from candidates c where q.id=c.id returning q.id
)
insert into question_competencies(question_id,competency_key,position)
select c.id,tag.key,(tag.ordinality-1)::integer from candidates c join updated u on u.id=c.id
cross join lateral unnest(c.competency_keys) with ordinality as tag(key,ordinality)
on conflict (question_id,competency_key) do nothing;

-- Full-schema inclusion: 20261105_track_integrity.sql
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

-- Full-schema inclusion: 20261105_practice_integrity.sql
-- Preserve all existing rows. Invalid tag positions require explicit repair; never deduplicate here.
do $$ begin
 if exists(select 1 from question_competencies group by question_id,position having count(*) > 1) then
   raise exception 'Duplicate competency positions: review existing data before enabling insights';
 end if;
end $$;
create unique index if not exists question_competencies_position_uq on question_competencies(question_id,position);

-- Owning a session must not permit attaching an answer to another user's private question.
drop policy if exists pa_all on practice_answers;
create policy pa_all on practice_answers for all
 using (exists(select 1 from practice_sessions s where s.id=session_id and s.user_id=auth.uid()))
 with check (
   exists(select 1 from practice_sessions s where s.id=session_id and s.user_id=auth.uid())
   and exists(select 1 from questions q where q.id=question_id and (q.user_id is null or q.user_id=auth.uid()))
 );

-- Full-schema inclusion: 20261105_version_immutability.sql
-- Preserve version content/identity and submission receipts, including legacy submitted flags.
-- Users can explicitly delete a parent application/item; its DB cascade still removes history.
create or replace function public.protect_answer_version_history() returns trigger
language plpgsql set search_path = pg_catalog, public as $$
begin
 if TG_OP = 'UPDATE' then
   if (NEW.id,NEW.essay_item_id,NEW.version_no,NEW.content,NEW.char_count,NEW.source,NEW.created_at)
      is distinct from
      (OLD.id,OLD.essay_item_id,OLD.version_no,OLD.content,OLD.char_count,OLD.source,OLD.created_at)
      or (OLD.is_submitted and not NEW.is_submitted) then
     raise exception 'Answer version history is immutable; save a new version' using errcode='23514';
   end if;
   return NEW;
 end if;
 if exists(select 1 from public.essay_items e where e.id=OLD.essay_item_id) then
   raise exception 'Delete the parent essay or application explicitly' using errcode='23514';
 end if;
 return OLD;
end $$;
drop trigger if exists answer_versions_history_guard on answer_versions;
create trigger answer_versions_history_guard before update or delete on answer_versions
 for each row execute function public.protect_answer_version_history();
