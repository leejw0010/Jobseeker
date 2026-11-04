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
