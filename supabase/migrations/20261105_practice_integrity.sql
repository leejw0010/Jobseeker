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
