-- =============================================================================
-- 0019 · The gallery is the plant's portraits, not one unused context.
--
-- Migration 0018 added ordering and the last-image rule for `context_type =
-- 'gallery'`, because that is the word section 20 uses. Against the data, that set
-- is empty and always has been:
--
--     identification  visible   44
--     health          visible    3
--     gallery         visible    0
--
-- No code path uploads with the `gallery` context. Add Plant sends
-- `identification`, a health check sends `health`, and `gallery` is only the
-- endpoint's default, which nothing takes. So 0018's trigger could never fire and
-- its ordering covered nothing a user has ever seen.
--
-- The application had already drawn the right line elsewhere: `upload_image` treats
-- gallery and identification together as "depicts the plant" when it chooses a
-- plant's first main image, and excludes health, because a close-up of a damaged
-- leaf is evidence rather than a portrait. This migration makes the gallery rules
-- agree with that, so the set a user sees, the set they can reorder, and the set
-- protected from deletion are one set.
--
-- 0018 is left as it stands rather than edited: it is already applied, and an
-- applied migration is a record of what the database was asked to do.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- One order across the portraits, rather than one per context.
--
-- 0018 numbered per (plant_id, context_type), which would give a plant holding both
-- kinds two images at position 1. Nothing has both today, so this renumbers a set
-- that is currently one context deep - but it makes the invariant true from the
-- start rather than the first time somebody uploads.
-- -----------------------------------------------------------------------------

with ordered as (
  select id,
         row_number() over (
           partition by plant_id
           order by display_order, created_at, id
         ) as position
    from public.plant_images
   where context_type in ('gallery', 'identification')
)
update public.plant_images t
   set display_order = ordered.position
  from ordered
 where t.id = ordered.id
   and t.display_order is distinct from ordered.position;

comment on column public.plant_images.display_order is
  'Gallery position, ascending, across a plant''s portraits (gallery and '
  'identification together). Not unique per plant: ties break on created_at, and '
  'requiring uniqueness would turn every reorder into a constraint dance.';

-- -----------------------------------------------------------------------------
-- An active plant keeps at least one photograph of itself.
--
-- Renamed rather than redefined in place. The old name says `gallery`, and a
-- function whose name names the wrong set is how the next reader repeats this
-- mistake.
-- -----------------------------------------------------------------------------

drop trigger if exists plant_images_keep_last_gallery on public.plant_images;
drop trigger if exists plant_images_keep_last_gallery_on_hide on public.plant_images;
drop function if exists public.refuse_last_gallery_image();

create function public.refuse_last_portrait_image()
returns trigger
language plpgsql
as $$
declare
  plant_status public.plant_status;
  remaining integer;
begin
  -- Health images are evidence for a single check and are not portraits, so they
  -- are not what keeps a plant legal and removing the last of them is allowed.
  if old.context_type not in ('gallery', 'identification') or not old.user_visible then
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
     and context_type in ('gallery', 'identification')
     and user_visible
     and id <> old.id;

  if remaining = 0 then
    raise exception 'An active plant must keep at least one photograph of itself.'
      using errcode = 'check_violation';
  end if;

  return coalesce(new, old);
end;
$$;

create trigger plant_images_keep_last_portrait
  before delete on public.plant_images
  for each row
  execute function public.refuse_last_portrait_image();

-- The same rule on the hide path. An AI-used image is never physically deleted
-- (FINAL section 20) - removing it is an UPDATE setting `user_visible` false - and
-- that is the same intent with a different statement. This matters more here than
-- it did in 0018: an identification image has been consumed by the identification,
-- so `ai_used` is true for every one of the 44, and the hide path is the only route
-- their removal ever takes.
create trigger plant_images_keep_last_portrait_on_hide
  before update of user_visible on public.plant_images
  for each row
  when (old.user_visible and not new.user_visible)
  execute function public.refuse_last_portrait_image();

comment on function public.refuse_last_portrait_image is
  'Section 20: an active plant must keep at least one visible photograph of itself '
  '(gallery or identification context). Health images are evidence for one check '
  'and do not count; hidden rows retained for AI audit do not count either.';

-- The gallery is read across both contexts now, so the index leads with the plant
-- and the order rather than sitting behind an equality on context_type.
drop index if exists public.idx_plant_images_gallery_order;

create index idx_plant_images_gallery_order
  on public.plant_images (plant_id, display_order, created_at)
  where user_visible and context_type in ('gallery', 'identification');
