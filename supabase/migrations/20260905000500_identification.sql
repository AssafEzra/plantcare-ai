-- =============================================================================
-- 0005 · Identification history.
--
-- Spec: DATABASE_SCHEMA "identifications", "identification_candidates"
--       FINAL_SPECIFICATION §8 (add plant), §9 (identification agent), §25
--
-- The Identification Agent never changes plants.species_id. Confirmation is an
-- application/orchestration action, and nothing here may imply otherwise.
--
-- Forward reference: identifications.agent_request_id points at agent_requests,
-- which is created with the AI infrastructure in a later migration. The column
-- exists now; the foreign key is added there. Recorded so it is not mistaken for
-- an oversight.
-- =============================================================================

create table public.identifications (
  id                  uuid                  primary key default gen_random_uuid(),
  user_id             uuid                  not null references public.profiles (id) on delete cascade,
  plant_id            uuid                  not null references public.plants (id) on delete cascade,
  -- FK added with agent_requests (see header note).
  agent_request_id    uuid,
  status              identification_status not null,
  method              identification_method not null default 'AI',
  primary_species_id  uuid                  references public.species (id) on delete set null,
  confidence_score    numeric(4, 3),
  confidence_level    confidence_level,
  image_quality       text,
  user_description    text,
  request_more_photos boolean               not null default false,
  wikipedia_url       text,
  raw_result          jsonb,
  created_at          timestamptz           not null default now(),

  -- A18: the score is a 0.000-1.000 probability. confidence_level is derived from
  -- it in Python (HIGH >= 0.85, MEDIUM >= 0.60), never taken from model output.
  constraint identifications_confidence_score_range
    check (confidence_score is null or confidence_score between 0 and 1),

  -- FINAL §25: a failed AI result must never become an authoritative
  -- identification. A non-SUCCESS row therefore cannot carry a species or a
  -- confidence verdict, which makes "AI failure creates no authoritative record"
  -- a database guarantee rather than a convention in application code.
  constraint identifications_failure_carries_no_verdict
    check (
      status = 'SUCCESS'
      or (primary_species_id is null and confidence_level is null)
    ),

  -- The Wikipedia URL is only ever written after verify_wikipedia_page() confirms
  -- a real page (FINAL §23); this rejects an invented or relative value outright.
  constraint identifications_wikipedia_url_shape
    check (wikipedia_url is null or wikipedia_url ~ '^https://[a-z]{2,}\.wikipedia\.org/')
);

comment on table public.identifications is
  'Append-oriented identification history. Re-identification adds a row; the '
  'previous identification is retained (FINAL §8).';

create index idx_identifications_plant on public.identifications (plant_id, created_at desc);
create index idx_identifications_user on public.identifications (user_id, created_at desc);
create index idx_identifications_agent_request
  on public.identifications (agent_request_id)
  where agent_request_id is not null;

-- -----------------------------------------------------------------------------
-- identification_candidates
--
-- species_id is nullable and the raw names are stored alongside it (plan decision
-- 2). Candidates come straight from model output, so materialising a species row
-- for each one would let every low-confidence hallucinated binomial permanently
-- pollute the global taxonomy table. The species is created only at confirm time,
-- from the candidate the user actually chose.
-- -----------------------------------------------------------------------------
create table public.identification_candidates (
  id                uuid        primary key default gen_random_uuid(),
  identification_id uuid        not null references public.identifications (id) on delete cascade,
  species_id        uuid        references public.species (id) on delete set null,
  scientific_name   text        not null,
  common_name       text,
  rank              smallint    not null,
  confidence_score  numeric(4, 3),
  created_at        timestamptz not null default now(),

  constraint identification_candidates_rank_range check (rank between 1 and 3),
  constraint identification_candidates_confidence_range
    check (confidence_score is null or confidence_score between 0 and 1),
  constraint identification_candidates_scientific_name_not_blank
    check (length(btrim(scientific_name)) > 0),
  -- One primary candidate and up to two alternatives (FINAL §8).
  constraint identification_candidates_unique_rank unique (identification_id, rank)
);

comment on column public.identification_candidates.species_id is
  'Normally null. Populated only when the name already matched a known species at '
  'the time the candidates were stored; the authoritative link is made at confirm.';

create index idx_identification_candidates_identification
  on public.identification_candidates (identification_id, rank);

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
alter table public.identifications            enable row level security;
alter table public.identification_candidates  enable row level security;

create policy identifications_select_own
  on public.identifications for select
  to authenticated
  using (user_id = auth.uid());

create policy identifications_insert_own
  on public.identifications for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.plants p
      where p.id = identifications.plant_id and p.user_id = auth.uid()
    )
  );

-- No UPDATE or DELETE policy for users: identification history is append-oriented
-- (FINAL §19). A correction creates a new row rather than rewriting an old one.

create policy identifications_select_admin
  on public.identifications for select
  to authenticated
  using (public.is_admin());

-- Candidates carry no user_id; ownership is proven through the identification.
create policy identification_candidates_select_own
  on public.identification_candidates for select
  to authenticated
  using (
    exists (
      select 1 from public.identifications i
      where i.id = identification_candidates.identification_id
        and i.user_id = auth.uid()
    )
  );

create policy identification_candidates_insert_own
  on public.identification_candidates for insert
  to authenticated
  with check (
    exists (
      select 1 from public.identifications i
      where i.id = identification_candidates.identification_id
        and i.user_id = auth.uid()
    )
  );

create policy identification_candidates_select_admin
  on public.identification_candidates for select
  to authenticated
  using (public.is_admin());
