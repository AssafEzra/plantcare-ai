-- =============================================================================
-- 0023 · The order a user puts their plants in.
--
-- "My Plants" has always been `created_at desc`, with a sort control offering name
-- and health as alternatives. None of them is the order a person actually wants:
-- the plant by the kitchen window that needs looking at every day belongs at the
-- top, and no attribute of the row knows that.
--
-- Additive, like 0018 which did the same job for a plant's photographs. No column
-- changes type, nothing is dropped, and every existing row is given the position it
-- already occupies on screen.
--
-- Deliberately NOT unique per user, and for the reason 0018 sets out at length: a
-- unique (user_id, display_order) index turns every reorder into a dance around the
-- constraint - move A out of the way, move B into its slot, move A back - and a drag
-- that reverses twenty plants would need a temporary value nothing can collide with.
-- Ordering is presentation. A duplicate shows two plants in an arbitrary but stable
-- order rather than corrupting anything, and `created_at` breaks the tie.
-- =============================================================================

alter table public.plants
  add column display_order integer not null default 0;

comment on column public.plants.display_order is
  'Position in the owner''s list, ascending. Not unique per user: ties break on '
  'created_at desc, and requiring uniqueness would turn every reorder into a '
  'constraint dance. Presentation only - nothing about care or scheduling reads it.';

-- Existing rows keep the order they are already shown in, which is newest first.
-- Descending on purpose: `list_for_user` ordered by `created_at desc`, so numbering
-- ascending here would silently reverse every user's list the day this ships.
with ordered as (
  select id,
         row_number() over (
           partition by user_id
           order by created_at desc, id
         ) as position
    from public.plants
)
update public.plants p
   set display_order = ordered.position
  from ordered
 where p.id = ordered.id;

-- The list is always read in this order, so the index carries it. `created_at desc`
-- is part of the key because it is the tie-breaker, not an afterthought.
create index idx_plants_user_order
  on public.plants (user_id, display_order, created_at desc);
