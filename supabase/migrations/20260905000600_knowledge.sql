-- =============================================================================
-- 0006 · Knowledge: drafts, published versions, sources and user error reports.
--
-- Spec: DATABASE_SCHEMA "knowledge_drafts", "knowledge_versions",
--       "knowledge_sources", "approved_sources", "knowledge_reports"
--       FINAL_SPECIFICATION §10 (knowledge base), §11 (knowledge agent), §29 (admin)
--
-- Knowledge is global, species-based and NOT user-editable. Users read published
-- versions and may report a suspected error; everything else is admin-only.
--
-- Correction to the implementation plan, recorded per FINAL §37
-- -----------------------------------------------------------
-- The plan's invariants table listed `knowledge_versions` as row-immutable. It
-- cannot be: `is_current` must flip to false when a newer version is published,
-- and the schema mandates that flag plus a partial unique index. This is the same
-- conflation already corrected for `care_plan_versions` — the immutability that
-- matters is of *content*, not of the whole row.
--
-- So: UPDATE may touch `is_current` and nothing else, and DELETE is refused
-- outright, because FINAL §29 says historical published versions are never
-- deleted.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- approved_sources (DATABASE_SCHEMA) — the domain allow-list the Knowledge Agent
-- prefers, and against which retrieved URLs are classified.
-- -----------------------------------------------------------------------------
create table public.approved_sources (
  id               uuid        primary key default gen_random_uuid(),
  name             text        not null,
  domain           text        not null,
  source_type      text,
  reliability_level smallint,
  notes            text,
  is_enabled       boolean     not null default true,
  created_by       uuid        references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint approved_sources_name_not_blank check (length(btrim(name)) > 0),
  -- Stored bare and lowercase ("rhs.org.uk", not "https://www.rhs.org.uk/"), because
  -- classification is a suffix match against a retrieved URL's host.
  constraint approved_sources_domain_shape
    check (domain ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'),
  constraint approved_sources_reliability_range
    check (reliability_level is null or reliability_level between 1 and 5)
);

create unique index approved_sources_domain_key on public.approved_sources (domain);
create index idx_approved_sources_enabled on public.approved_sources (domain) where is_enabled;

create trigger approved_sources_set_updated_at
  before update on public.approved_sources
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- knowledge_drafts (DATABASE_SCHEMA)
--
-- Drafts are working material: mutable, admin-visible only. The Knowledge Agent
-- never publishes (FINAL §11); publication is an explicit admin action that
-- creates a row in knowledge_versions.
--
-- Forward reference: research_request_id points at agent_requests, created with
-- the AI infrastructure. The column exists now; the FK is added there.
-- -----------------------------------------------------------------------------
create table public.knowledge_drafts (
  id                  uuid                  primary key default gen_random_uuid(),
  species_id          uuid                  not null references public.species (id) on delete cascade,
  language            text                  not null default 'he',
  status              knowledge_draft_status not null default 'DRAFT',
  initiated_by        uuid                  references public.profiles (id) on delete set null,
  research_request_id uuid,
  content             jsonb,
  research_notes      text,
  admin_note          text,
  created_at          timestamptz           not null default now(),
  updated_at          timestamptz           not null default now(),

  constraint knowledge_drafts_language_shape check (language ~ '^[a-z]{2}$')
);

comment on column public.knowledge_drafts.content is
  'The 14 sections from FINAL §10: Identification, Description, Light, Watering, '
  'Soil, Temperature, Humidity, Fertilization, Repotting, Pruning, Propagation, '
  'Common Problems, Toxicity/Safety, Sources. Shape validated by the Pydantic '
  'KnowledgeContent model (A16), not by the database.';

-- At most one draft in flight per species and language. A second concurrent
-- research run would race to publish two versions of the same knowledge.
create unique index knowledge_drafts_one_open_per_species
  on public.knowledge_drafts (species_id, language)
  where status in ('DRAFT', 'RESEARCHING', 'READY_FOR_REVIEW');

create index idx_knowledge_drafts_status on public.knowledge_drafts (status, updated_at desc);

create trigger knowledge_drafts_set_updated_at
  before update on public.knowledge_drafts
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- knowledge_versions (DATABASE_SCHEMA)
-- -----------------------------------------------------------------------------
create table public.knowledge_versions (
  id             uuid        primary key default gen_random_uuid(),
  species_id     uuid        not null references public.species (id) on delete restrict,
  language       text        not null default 'he',
  version_number integer     not null,
  content        jsonb       not null,
  source_summary jsonb,
  is_current     boolean     not null default false,
  published_by   uuid        references public.profiles (id) on delete set null,
  published_at   timestamptz not null default now(),
  created_at     timestamptz not null default now(),

  constraint knowledge_versions_version_number_positive check (version_number >= 1),
  constraint knowledge_versions_language_shape check (language ~ '^[a-z]{2}$')
);

-- Version numbers are dense and per species+language.
create unique index knowledge_versions_number_key
  on public.knowledge_versions (species_id, language, version_number);

-- The one-current-version invariant (DATABASE_SCHEMA). Keyed on language as well
-- as species, so a future English localisation can publish independently.
create unique index knowledge_versions_one_current
  on public.knowledge_versions (species_id, language)
  where is_current;

create index idx_knowledge_versions_species
  on public.knowledge_versions (species_id, version_number desc);

-- Content immutability. `is_current` is deliberately absent from the protected
-- list: publishing a newer version must be able to demote its predecessor.
create trigger knowledge_versions_content_immutable
  before update on public.knowledge_versions
  for each row execute function public.reject_content_mutation(
    'species_id', 'language', 'version_number', 'content', 'source_summary',
    'published_by', 'published_at'
  );

-- FINAL §29: historical published versions are never deleted, by anyone.
create trigger knowledge_versions_no_delete
  before delete on public.knowledge_versions
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- knowledge_sources (DATABASE_SCHEMA)
--
-- Provenance for a published version. Every row here has already survived the
-- deterministic Python verification step (fetch, HTTP 200, relevance, domain
-- match) — the model's self-report is never authoritative (FINAL §23).
-- -----------------------------------------------------------------------------
create table public.knowledge_sources (
  id                   uuid                   primary key default gen_random_uuid(),
  knowledge_version_id uuid                   not null references public.knowledge_versions (id) on delete restrict,
  approved_source_id   uuid                   references public.approved_sources (id) on delete set null,
  source_class         knowledge_source_class not null,
  title                text,
  url                  text,
  publisher            text,
  retrieved_at         timestamptz,
  citation_text        text,
  notes                text,
  created_at           timestamptz            not null default now(),

  -- An APPROVED or EXTERNAL_UNAPPROVED source is by definition an external claim
  -- and must carry the URL that was actually fetched and verified. Only
  -- AI_GENERATED_REQUIRES_VERIFICATION may lack one — that is what the class means.
  constraint knowledge_sources_external_requires_url
    check (
      source_class = 'AI_GENERATED_REQUIRES_VERIFICATION'
      or (url is not null and url ~ '^https?://')
    ),
  -- Conversely, an unverified AI claim must not masquerade as a cited source.
  constraint knowledge_sources_ai_generated_has_no_approved_source
    check (
      source_class <> 'AI_GENERATED_REQUIRES_VERIFICATION'
      or approved_source_id is null
    ),
  -- Only a domain match against approved_sources may be classified APPROVED.
  constraint knowledge_sources_approved_requires_link
    check (source_class <> 'APPROVED' or approved_source_id is not null)
);

create index idx_knowledge_sources_version on public.knowledge_sources (knowledge_version_id);
create index idx_knowledge_sources_approved
  on public.knowledge_sources (approved_source_id)
  where approved_source_id is not null;

-- Sources belong to an immutable version and are themselves immutable.
create trigger knowledge_sources_immutable
  before update or delete on public.knowledge_sources
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- knowledge_reports (DATABASE_SCHEMA) — users may report a suspected error.
-- -----------------------------------------------------------------------------
create table public.knowledge_reports (
  id                   uuid        primary key default gen_random_uuid(),
  user_id              uuid        not null references public.profiles (id) on delete cascade,
  plant_id             uuid        references public.plants (id) on delete set null,
  species_id           uuid        references public.species (id) on delete cascade,
  knowledge_version_id uuid        references public.knowledge_versions (id) on delete set null,
  report_text          text        not null,
  status               text        not null default 'OPEN',
  admin_note           text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),

  constraint knowledge_reports_text_not_blank check (length(btrim(report_text)) > 0),
  constraint knowledge_reports_status_known
    check (status in ('OPEN', 'REVIEWING', 'ACTIONED', 'DISMISSED')),
  -- A report that names nothing is unactionable.
  constraint knowledge_reports_has_a_subject
    check (species_id is not null or knowledge_version_id is not null)
);

create index idx_knowledge_reports_status on public.knowledge_reports (status, created_at desc);
create index idx_knowledge_reports_user on public.knowledge_reports (user_id, created_at desc);

create trigger knowledge_reports_set_updated_at
  before update on public.knowledge_reports
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
alter table public.approved_sources   enable row level security;
alter table public.knowledge_drafts   enable row level security;
alter table public.knowledge_versions enable row level security;
alter table public.knowledge_sources  enable row level security;
alter table public.knowledge_reports  enable row level security;

-- approved_sources: admin-only, both directions (FINAL §29). Users never need it —
-- knowledge_sources already carries title, url and publisher for provenance display.
create policy approved_sources_admin_all
  on public.approved_sources for all
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- knowledge_drafts: admin-only. A user's visibility into pending research is the
-- plant's KNOWLEDGE_PENDING status, not the draft itself.
create policy knowledge_drafts_admin_all
  on public.knowledge_drafts for all
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- knowledge_versions: users read the current published version only.
create policy knowledge_versions_select_current
  on public.knowledge_versions for select
  to authenticated
  using (is_current);

-- The admin read-all policy. Without this, an admin using a JWT-scoped client
-- would be unable to read version history — which is exactly what the Admin
-- Panel's "Published Knowledge · history" view needs.
create policy knowledge_versions_select_admin
  on public.knowledge_versions for select
  to authenticated
  using (public.is_admin());

create policy knowledge_versions_insert_admin
  on public.knowledge_versions for insert
  to authenticated
  with check (public.is_admin());

create policy knowledge_versions_update_admin
  on public.knowledge_versions for update
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- No DELETE policy for anyone, reinforcing the trigger above.

-- knowledge_sources: visible with the version they belong to.
create policy knowledge_sources_select_with_current_version
  on public.knowledge_sources for select
  to authenticated
  using (
    exists (
      select 1 from public.knowledge_versions v
      where v.id = knowledge_sources.knowledge_version_id and v.is_current
    )
  );

create policy knowledge_sources_admin_all
  on public.knowledge_sources for all
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- knowledge_reports: a user files and reads their own; admins see and triage all.
create policy knowledge_reports_select_own
  on public.knowledge_reports for select
  to authenticated
  using (user_id = auth.uid());

create policy knowledge_reports_insert_own
  on public.knowledge_reports for insert
  to authenticated
  with check (user_id = auth.uid());

-- Users deliberately cannot UPDATE: status and admin_note are the admin's triage
-- record, not something the reporter may edit after filing.
create policy knowledge_reports_admin_all
  on public.knowledge_reports for all
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());
