-- JobSeeker ② Practice P0: 녹음 동의·원본 보관 기한, 세션 종료 자동 디브리프
-- 이미 schema.sql을 실행한 Supabase 프로젝트에서 SQL Editor로 한 번 실행하세요. 다시 실행해도 안전합니다.
-- (새로 만드는 프로젝트는 schema.sql만 실행하면 이 내용이 모두 들어 있습니다.)
-- 면접 코칭 테이블은 20261015_interview_coaching.sql이 만듭니다. 두 파일은 서로 의존하지 않습니다.

-- ───────── 세션: 자동 디브리프 ─────────
alter table practice_sessions add column if not exists debrief jsonb;
alter table practice_sessions add column if not exists debrief_status text not null default 'none';
alter table practice_sessions add column if not exists debrief_started_at timestamptz;
do $$ begin
  alter table practice_sessions add constraint practice_sessions_debrief_status_check
    check (debrief_status in ('none','pending','done','failed','unavailable'));
exception when duplicate_object then null;
end $$;

-- ───────── 답변: 녹음 시각·원본 보관 기한 ─────────
alter table practice_answers add column if not exists recorded_at timestamptz;
alter table practice_answers add column if not exists audio_expires_at timestamptz;
alter table practice_answers add column if not exists audio_deleted_at timestamptz;
create index if not exists practice_answers_audio_expiry_idx
  on practice_answers(audio_expires_at) where audio_path is not null;

-- ───────── 녹음 동의·원본 보관 설정 ─────────
create table if not exists user_settings (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  consented_at  timestamptz,                -- null = 녹음 미동의(또는 철회)
  keep_audio    boolean not null default false,  -- true면 전사 후에도 원본 보관(보관 기한 뒤 자동 삭제)
  updated_at    timestamptz not null default now()
);
alter table user_settings enable row level security;
drop policy if exists us_all on user_settings;
create policy us_all on user_settings for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ───────── 예전 행 보정 ─────────
-- 녹음이 있던 답변은 만든 시각을 녹음 시각으로 본다
update practice_answers set recorded_at = created_at
  where audio_path is not null and recorded_at is null;
-- 기존 원본 녹음에도 보관 기한을 붙인다. 30일은 AUDIO_RETENTION_DAYS 기본값과 같다(바꿨다면 함께 바꾸세요)
update practice_answers set audio_expires_at = created_at + interval '30 days'
  where audio_path is not null and audio_expires_at is null;
