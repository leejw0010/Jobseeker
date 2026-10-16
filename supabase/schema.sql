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
  debrief_started_at timestamptz           -- 디브리프 작업(답변 점검 + 요약) 시작 시각(오래된 작업은 다시 시작)
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
