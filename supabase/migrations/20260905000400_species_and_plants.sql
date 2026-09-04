-- =============================================================================
-- 0004 · Species (taxonomy only), plants, environment and images.
--
-- Spec: DATABASE_SCHEMA "species", "plants", "plant_environments", "plant_images"
--       FINAL_SPECIFICATION §7 (lifecycle), §18 (environment), §20 (images), §21
--
-- Ordering note (recorded per FINAL §37): the plan placed `species` with the
-- knowledge tables, but plants, identifications and identification_candidates all
-- reference it. Creating it here avoids three forward-declared foreign keys.
-- Only the taxonomy entity moves; knowledge_drafts / knowledge_versions /
-- knowledge_sources / approved_sources / knowledge_reports stay in the next
-- migration.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Scientific-name normalisation (A23)
--
-- Without this, "Monstera deliciosa", "monstera deliciosa" and "Monstera
-- deliciosa Liebm." become three species with three separate Knowledge lineages,
-- which defeats the "existing species reuses published Knowledge" journey in
-- FINAL §34. The risk runs one way — over-aggressive stripping would merge
-- genuinely distinct taxa — so authorship is only removed after a binomial has
-- already been matched, and infraspecific ranks are preserved.
-- -----------------------------------------------------------------------------
create or replace function public.normalize_scientific_name(input text)
returns text
language plpgsql
immutable
as $fn$
declare
  s           text;
  parts       text[];
  out_parts   text[];
  rank_marker text;
begin
  if input is null then
    return null;
  end if;

  s := lower(normalize(input, NFKC));
  s := regexp_replace(s, '\(.*?\)', ' ', 'g');          -- parenthetical authorship
  s := regexp_replace(s, '[^a-z×\.\s-]', ' ', 'g');     -- keep letters, hybrid sign, dot, hyphen
  s := regexp_replace(s, '\s+', ' ', 'g');
  s := btrim(s);

  if s = '' then
    return null;
  end if;

  parts := string_to_array(s, ' ');
  out_parts := array[parts[1]];                          -- genus

  if array_length(parts, 1) >= 2 then
    out_parts := out_parts || parts[2];                  -- specific epithet
  end if;

  -- Retain an infraspecific rank when one is present: "var." / "subsp." / "f."
  -- distinguish real taxa and must not be collapsed away.
  if array_length(parts, 1) >= 4 then
    rank_marker := rtrim(parts[3], '.');
    if rank_marker in ('var', 'subsp', 'ssp', 'f', 'forma', 'cv') then
      out_parts := out_parts || (rank_marker || '.') || parts[4];
    end if;
  end if;

  return array_to_string(out_parts, ' ');
end;
$fn$;

comment on function public.normalize_scientific_name(text) is
  'Collapses spelling and authorship variants of a scientific name to one key, so '
  'a species has exactly one Knowledge lineage (A23). Authorship is stripped only '
  'after a binomial matches; infraspecific ranks are preserved.';

-- -----------------------------------------------------------------------------
-- species (DATABASE_SCHEMA "species") — MVP is Species-only; Cultivar is future.
-- -----------------------------------------------------------------------------
create table public.species (
  id              uuid primary key default gen_random_uuid(),
  scientific_name text        not null,
  normalized_name text        not null,
  common_name     text,
  family          text,
  genus           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint species_scientific_name_not_blank check (length(btrim(scientific_name)) > 0)
);

-- The uniqueness constraint lives on the normalised value, not the raw name.
create unique index species_normalized_name_key on public.species (normalized_name);
create index idx_species_scientific_name on public.species (scientific_name);

create or replace function public.species_set_normalized_name()
returns trigger
language plpgsql
as $fn$
begin
  new.normalized_name := public.normalize_scientific_name(new.scientific_name);
  if new.normalized_name is null then
    raise exception 'scientific_name % does not normalise to a usable key',
      new.scientific_name using errcode = 'check_violation';
  end if;
  if new.genus is null then
    new.genus := split_part(new.normalized_name, ' ', 1);
  end if;
  return new;
end;
$fn$;

-- A trigger rather than a generated column, so normalisation cannot be bypassed
-- by a direct insert that supplies its own normalized_name.
create trigger species_set_normalized_name
  before insert or update of scientific_name on public.species
  for each row execute function public.species_set_normalized_name();

create trigger species_set_updated_at
  before update on public.species
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- upsert_species()
--
-- The confirm-identification workflow needs to create a species row while running
-- under the *user's* JWT (plan decision 2: species is created at confirm, from a
-- candidate). Granting authenticated users a blanket INSERT on a global taxonomy
-- table would let any client write arbitrary rows, so the write is funnelled
-- through this SECURITY DEFINER function instead: it normalises, deduplicates,
-- and returns the existing row when the name is already known.
-- -----------------------------------------------------------------------------
create or replace function public.upsert_species(
  p_scientific_name text,
  p_common_name     text default null,
  p_family          text default null,
  p_genus           text default null
)
returns public.species
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  normalized text;
  result     public.species;
begin
  if auth.uid() is null then
    raise exception 'authentication required' using errcode = 'insufficient_privilege';
  end if;

  normalized := public.normalize_scientific_name(p_scientific_name);
  if normalized is null then
    raise exception 'scientific_name % is not a usable species name', p_scientific_name
      using errcode = 'check_violation';
  end if;

  select * into result from public.species s where s.normalized_name = normalized;
  if found then
    -- Fill in details we did not have before, but never overwrite existing values:
    -- the first-seen scientific_name stays canonical for display.
    update public.species s
       set common_name = coalesce(s.common_name, p_common_name),
           family      = coalesce(s.family, p_family),
           genus       = coalesce(s.genus, p_genus)
     where s.id = result.id
     returning * into result;
    return result;
  end if;

  insert into public.species (scientific_name, common_name, family, genus)
  values (btrim(p_scientific_name), p_common_name, p_family, p_genus)
  returning * into result;

  return result;
end;
$fn$;

revoke all on function public.upsert_species(text, text, text, text) from public;
grant execute on function public.upsert_species(text, text, text, text)
  to authenticated, service_role;

-- -----------------------------------------------------------------------------
-- plants (DATABASE_SCHEMA "plants")
-- -----------------------------------------------------------------------------
create table public.plants (
  id                    uuid         primary key default gen_random_uuid(),
  user_id               uuid         not null references public.profiles (id) on delete cascade,
  -- Nullable until the user confirms identification: the Add Plant flow creates
  -- the plant before the user names it (FINAL §3 step 5 comes after confirm).
  name                  text,
  species_id            uuid         references public.species (id) on delete restrict,
  status                plant_status  not null default 'PENDING_IDENTIFICATION',
  current_health_status health_status  not null default 'UNKNOWN',
  -- FK added after plant_images exists (circular reference).
  main_image_id         uuid,
  notes                 text,
  archived_at           timestamptz,
  created_at            timestamptz  not null default now(),
  updated_at            timestamptz  not null default now(),

  -- Archive is the normal user action, not deletion (FINAL §21). Keeping the flag
  -- and the timestamp in agreement prevents a plant that is archived by status but
  -- still appears active by timestamp, or the reverse.
  constraint plants_archived_at_matches_status
    check ((status = 'ARCHIVED') = (archived_at is not null)),

  constraint plants_name_not_blank
    check (name is null or length(btrim(name)) > 0)
);

comment on column public.plants.species_id is
  'Null until identification is confirmed. ON DELETE RESTRICT: a species with '
  'plants attached must never be removed out from under them.';

create index idx_plants_user_status on public.plants (user_id, status);
create index idx_plants_user_health on public.plants (user_id, current_health_status);
create index idx_plants_species on public.plants (species_id) where species_id is not null;

create trigger plants_set_updated_at
  before update on public.plants
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- plant_environments (DATABASE_SCHEMA) — exactly one current row per plant.
-- History is not kept here; every update also writes a system_events row
-- (ENVIRONMENT_CHANGED), which is what Plant History renders (FINAL §19).
-- -----------------------------------------------------------------------------
create table public.plant_environments (
  id               uuid        primary key default gen_random_uuid(),
  plant_id         uuid        not null unique references public.plants (id) on delete cascade,
  location_type    location_type,
  light_level      light_level,
  light_direction  light_direction,
  temperature_c    numeric(4, 1),
  humidity_percent numeric(5, 2),
  room             text,
  notes            text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  -- MVP units are °C and % (FINAL §18). These bounds reject transposed or
  -- mis-scaled input rather than feeding nonsense to the Care Agent.
  constraint plant_environments_temperature_range
    check (temperature_c is null or temperature_c between -50 and 60),
  constraint plant_environments_humidity_range
    check (humidity_percent is null or humidity_percent between 0 and 100)
);

comment on table public.plant_environments is
  'All fields optional: the Care Agent works with partial environment data and '
  'qualifies its recommendation when something important is missing (FINAL §18).';

create trigger plant_environments_set_updated_at
  before update on public.plant_environments
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- plant_images (DATABASE_SCHEMA) — metadata only; binaries live in Storage.
-- -----------------------------------------------------------------------------
create table public.plant_images (
  id                      uuid               primary key default gen_random_uuid(),
  user_id                 uuid               not null references public.profiles (id) on delete cascade,
  plant_id                uuid               not null references public.plants (id) on delete cascade,
  storage_path_original   text               not null,
  storage_path_processed  text,
  storage_path_thumbnail  text,
  mime_type               text               not null,
  size_bytes              bigint             not null,
  width                   integer,
  height                  integer,
  context_type            image_context_type not null,
  -- FINAL §20 retention: an AI-used image the user removes is hidden, not deleted.
  user_visible            boolean            not null default true,
  ai_used                 boolean            not null default false,
  retention_reason        text,
  created_at              timestamptz        not null default now(),

  constraint plant_images_mime_supported
    check (mime_type in ('image/jpeg', 'image/png', 'image/webp')),
  constraint plant_images_size_within_limit
    check (size_bytes > 0 and size_bytes <= 10485760),
  -- An image may only be hidden while carrying a reason, so retained rows are
  -- always explicable to an administrator reviewing them later.
  constraint plant_images_hidden_requires_reason
    check (user_visible or retention_reason is not null)
);

create index idx_plant_images_plant on public.plant_images (plant_id, created_at desc);
create index idx_plant_images_visible
  on public.plant_images (plant_id, context_type)
  where user_visible;

-- Deferred circular reference: a plant's main image must belong to that plant.
alter table public.plants
  add constraint plants_main_image_fk
  foreign key (main_image_id) references public.plant_images (id) on delete set null;

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
alter table public.species             enable row level security;
alter table public.plants              enable row level security;
alter table public.plant_environments  enable row level security;
alter table public.plant_images        enable row level security;

-- species: global reference data. Readable by everyone signed in; written only
-- through upsert_species() or by an administrator.
create policy species_select_authenticated
  on public.species for select
  to authenticated
  using (true);

create policy species_admin_write
  on public.species for all
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- plants: owner-only.
create policy plants_select_own
  on public.plants for select
  to authenticated
  using (user_id = auth.uid());

create policy plants_insert_own
  on public.plants for insert
  to authenticated
  with check (user_id = auth.uid());

create policy plants_update_own
  on public.plants for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- No DELETE policy: archive is the normal action (FINAL §21).

create policy plants_select_admin
  on public.plants for select
  to authenticated
  using (public.is_admin());

-- plant_environments: no user_id column, so ownership is proven through the plant.
create policy plant_environments_own
  on public.plant_environments for all
  to authenticated
  using (
    exists (
      select 1 from public.plants p
      where p.id = plant_environments.plant_id and p.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.plants p
      where p.id = plant_environments.plant_id and p.user_id = auth.uid()
    )
  );

-- plant_images: user_id is denormalised onto the row, but the plant must also
-- belong to the same user — otherwise a client could attach an image row to
-- someone else's plant while still passing the user_id check.
create policy plant_images_select_own
  on public.plant_images for select
  to authenticated
  using (user_id = auth.uid());

create policy plant_images_insert_own
  on public.plant_images for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.plants p
      where p.id = plant_images.plant_id and p.user_id = auth.uid()
    )
  );

create policy plant_images_update_own
  on public.plant_images for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy plant_images_delete_own
  on public.plant_images for delete
  to authenticated
  using (user_id = auth.uid() and not ai_used);

comment on policy plant_images_delete_own on public.plant_images is
  'AI-used images cannot be deleted even by their owner: FINAL §20 requires them '
  'retained for history and audit, hidden rather than removed.';

create policy plant_images_select_admin
  on public.plant_images for select
  to authenticated
  using (public.is_admin());
