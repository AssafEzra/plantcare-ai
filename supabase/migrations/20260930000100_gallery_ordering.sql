-- =============================================================================
-- 0018 · Gallery ordering.
--
-- The React migration's section 20 asks for a gallery the user can reorder by drag
-- and drop, and for an explicit "set as main" rather than "whichever was uploaded
-- first". `plants.main_image_id` already answers the second half; there was nothing
-- to answer the first with, so this adds it.
--
-- Approved as a backend change under the migration spec's section 5 exception and
-- recorded in docs/MIGRATION_AUDIT.md section 5. It is additive: no column changes
-- type, nothing is dropped, and every existing row gets an order derived from the
-- order it already appeared in.
--
-- Deliberately NOT unique per plant. A unique (plant_id, display_order) index would
-- make any reorder a multi-statement dance around the constraint - move A out of the
-- way, move B into its slot, move A back - and a drag that reverses ten images would
-- need a temporary value nobody can collide with. Ordering is presentation, and a
-- duplicate here shows two photographs in an arbitrary but stable order rather than
-- corrupting anything. `created_at` breaks the tie, so the result is deterministic.
-- =============================================================================

alter table public.plant_images
  add column display_order integer not null default 0;

comment on column public.plant_images.display_order is
  'Gallery position, ascending. Not unique per plant: ties break on created_at, and '
  'requiring uniqueness would turn every reorder into a constraint dance. Only '
  'meaningful for context_type = ''gallery''.';

-- Existing rows keep the order they already had on screen, which is oldest first.
-- Numbered per plant and per context, so an identification set and a gallery set do
-- not interleave.
with ordered as (
  select id,
         row_number() over (
           partition by plant_id, context_type
           order by created_at, id
         ) as position
    from public.plant_images
)
update public.plant_images t
   set display_order = ordered.position
  from ordered
 where t.id = ordered.id;

-- The gallery is always read in this order, so the index carries it.
create index idx_plant_images_gallery_order
  on public.plant_images (plant_id, context_type, display_order, created_at);

-- -----------------------------------------------------------------------------
-- An active plant keeps at least one gallery image.
--
-- Section 20: "An Active Plant must contain at least one Gallery image. The last
-- image cannot be deleted." This was not enforced anywhere - `delete_image` simply
-- set `main_image_id` to NULL when nothing remained, leaving an active plant with no
-- photograph at all.
--
-- A trigger rather than a check constraint: the rule spans two tables, and it has to
-- fire on delete of the *last* row rather than on the state of the row being
-- written. Hidden rows do not count - an AI-used image the user removed is retained
-- for audit but is not in their gallery any more (FINAL section 20), so it cannot be
-- the one image keeping the plant legal.
-- -----------------------------------------------------------------------------

create or replace function public.refuse_last_gallery_image()
returns trigger
language plpgsql
as $$
declare
  plant_status public.plant_status;
  remaining integer;
begin
  if old.context_type <> 'gallery' or not old.user_visible then
    return coalesce(new, old);
  end if;

  select status into plant_status from public.plants where id = old.plant_id;

  -- A plant being archived or deleted takes its images with it; the rule only
  -- protects a plant someone is still using.
  if plant_status is distinct from 'ACTIVE' then
    return coalesce(new, old);
  end if;

  -- Excluding this row: on a delete it is going away, on a hide it is about to
  -- stop being visible. Either way it cannot be the one that keeps the plant legal.
  select count(*) into remaining
    from public.plant_images
   where plant_id = old.plant_id
     and context_type = 'gallery'
     and user_visible
     and id <> old.id;

  if remaining = 0 then
    raise exception 'An active plant must keep at least one gallery image.'
      using errcode = 'check_violation';
  end if;

  return coalesce(new, old);
end;
$$;

create trigger plant_images_keep_last_gallery
  before delete on public.plant_images
  for each row
  execute function public.refuse_last_gallery_image();

-- The same rule on the hide path. An AI-used image is never physically deleted
-- (FINAL section 20) - removing it is an UPDATE setting `user_visible` false - and
-- that is the same intent with a different statement. Without this, the one route
-- the rule was written for would walk straight past it.
create trigger plant_images_keep_last_gallery_on_hide
  before update of user_visible on public.plant_images
  for each row
  when (old.user_visible and not new.user_visible)
  execute function public.refuse_last_gallery_image();

comment on function public.refuse_last_gallery_image is
  'Section 20: an active plant must keep at least one visible gallery image. Hidden '
  'rows retained for AI audit do not count towards it.';
