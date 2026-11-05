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
