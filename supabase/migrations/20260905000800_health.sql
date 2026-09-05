-- =============================================================================
-- 0008 · Health assessments, their images, findings and sources.
--
-- Spec: DATABASE_SCHEMA "health_assessments" … "health_recommendations"
--       FINAL_SPECIFICATION §16 (health agent)
--
-- Assessments are immutable: every successful Health Check updates the plant's
-- current status while previous assessments remain unchanged.
--
-- Gap closed here, recorded per FINAL §37: §16 lists `sources` as a required
-- output field of a HealthAssessment, and DEVELOPMENT_PROGRESS §16 has an
-- unchecked "Sources" item, but DATABASE_SCHEMA defines no table to hold them.
-- health_assessment_sources below mirrors knowledge_sources and reuses the same
-- deterministic verification pipeline.
-- =============================================================================

create table public.health_assessments (
  id                             uuid             primary key default gen_random_uuid(),
  user_id                        uuid             not null references public.profiles (id) on delete cascade,
  plant_id                       uuid             not null references public.plants (id) on delete cascade,
  -- FK added with agent_requests in the next migration.
  agent_request_id               uuid,
  overall_status                 health_status    not null,
  confidence_level               confidence_level,
  trend                          health_trend     not null default 'UNABLE_TO_DETERMINE',
  user_note                      text,
  requires_attention             boolean          not null default false,
  insufficient_information_reason text,
  raw_result                     jsonb,
  created_at                     timestamptz      not null default now(),

  -- FINAL §16: "If information is insufficient, save an UNKNOWN assessment with
  -- the reason." An UNKNOWN verdict with no explanation is useless to the user
  -- and indistinguishable from a bug.
  constraint health_assessments_unknown_has_a_reason
    check (overall_status <> 'UNKNOWN' or insufficient_information_reason is not null),

  -- A verdict of UNKNOWN cannot also carry a confidence level: the two would
  -- contradict each other on screen.
  constraint health_assessments_unknown_has_no_confidence
    check (overall_status <> 'UNKNOWN' or confidence_level is null)
);

comment on column public.health_assessments.trend is
  'Computed in Python from prior assessments (A11), never taken from model output: '
  'a trend over stored history is deterministic, so FINAL §1.4 says do not use an LLM.';

create index idx_health_assessments_plant on public.health_assessments (plant_id, created_at desc);
create index idx_health_assessments_user on public.health_assessments (user_id, created_at desc);

-- Immutable: a new check creates a new assessment (FINAL §16).
create trigger health_assessments_immutable
  before update or delete on public.health_assessments
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- health_assessment_images — MVP allows 1-4 images.
-- -----------------------------------------------------------------------------
create table public.health_assessment_images (
  health_assessment_id uuid        not null references public.health_assessments (id) on delete cascade,
  plant_image_id       uuid        not null references public.plant_images (id) on delete restrict,
  display_order        smallint    not null default 1,
  created_at           timestamptz not null default now(),

  primary key (health_assessment_id, plant_image_id),
  constraint health_assessment_images_order_range check (display_order between 1 and 4)
);

create unique index health_assessment_images_order_key
  on public.health_assessment_images (health_assessment_id, display_order);

-- The 1-4 rule spans rows, so a column CHECK cannot express it. A deferred
-- constraint trigger checks the count at commit, which is the only point at which
-- the set is complete. FINAL §16 requires at least one image and at most four.
create or replace function public.health_assessment_image_count_guard()
returns trigger
language plpgsql
as $fn$
declare
  assessment uuid := coalesce(new.health_assessment_id, old.health_assessment_id);
  n integer;
begin
  -- The assessment may have been deleted in this transaction (cascade); nothing
  -- to check in that case.
  if not exists (select 1 from public.health_assessments where id = assessment) then
    return null;
  end if;

  select count(*) into n
    from public.health_assessment_images
   where health_assessment_id = assessment;

  if n < 1 or n > 4 then
    raise exception
      'a health assessment must reference between 1 and 4 images, found %', n
      using errcode = 'check_violation';
  end if;
  return null;
end;
$fn$;

create constraint trigger health_assessment_images_count
  after insert or update or delete on public.health_assessment_images
  deferrable initially deferred
  for each row execute function public.health_assessment_image_count_guard();

-- -----------------------------------------------------------------------------
-- Findings. All three are immutable children of an immutable assessment.
-- -----------------------------------------------------------------------------
create table public.health_observations (
  id                   uuid             primary key default gen_random_uuid(),
  health_assessment_id uuid             not null references public.health_assessments (id) on delete cascade,
  observation_text     text             not null,
  confidence_level     confidence_level,
  created_at           timestamptz      not null default now(),

  constraint health_observations_text_not_blank check (length(btrim(observation_text)) > 0)
);

create table public.health_issues (
  id                   uuid             primary key default gen_random_uuid(),
  health_assessment_id uuid             not null references public.health_assessments (id) on delete cascade,
  issue_name           text             not null,
  severity             smallint,
  confidence_level     confidence_level,
  evidence             text,
  created_at           timestamptz      not null default now(),

  constraint health_issues_name_not_blank check (length(btrim(issue_name)) > 0),
  constraint health_issues_severity_range check (severity is null or severity between 1 and 5)
);

comment on table public.health_issues is
  'Possible issues, never definitive diagnosis (FINAL §16). Overall status and '
  'issue severity are separate concepts and must not be conflated.';

create table public.health_recommendations (
  id                            uuid        primary key default gen_random_uuid(),
  health_assessment_id          uuid        not null references public.health_assessments (id) on delete cascade,
  recommendation_text           text        not null,
  priority                      smallint,
  requires_care_plan_adjustment boolean     not null default false,
  created_at                    timestamptz not null default now(),

  constraint health_recommendations_text_not_blank
    check (length(btrim(recommendation_text)) > 0),
  constraint health_recommendations_priority_range
    check (priority is null or priority between 1 and 5)
);

comment on column public.health_recommendations.requires_care_plan_adjustment is
  'A flag only. The Health Agent cannot modify a Care Plan; it raises a proposal '
  'through the Care Agent, which the user must approve (FINAL §12).';

-- Sources — the gap this migration closes (FINAL §16 output field `sources`).
create table public.health_assessment_sources (
  id                   uuid                   primary key default gen_random_uuid(),
  health_assessment_id uuid                   not null references public.health_assessments (id) on delete cascade,
  source_class         knowledge_source_class not null,
  title                text,
  url                  text,
  publisher            text,
  retrieved_at         timestamptz,
  citation_text        text,
  created_at           timestamptz            not null default now(),

  -- Same provenance rule as knowledge_sources: an external claim must carry the
  -- URL that was actually fetched and verified.
  constraint health_assessment_sources_external_requires_url
    check (
      source_class = 'AI_GENERATED_REQUIRES_VERIFICATION'
      or (url is not null and url ~ '^https?://')
    )
);

create index idx_health_observations_assessment
  on public.health_observations (health_assessment_id);
create index idx_health_issues_assessment on public.health_issues (health_assessment_id);
create index idx_health_recommendations_assessment
  on public.health_recommendations (health_assessment_id);
create index idx_health_assessment_sources_assessment
  on public.health_assessment_sources (health_assessment_id);

create trigger health_observations_immutable
  before update or delete on public.health_observations
  for each row execute function public.reject_mutation();
create trigger health_issues_immutable
  before update or delete on public.health_issues
  for each row execute function public.reject_mutation();
create trigger health_recommendations_immutable
  before update or delete on public.health_recommendations
  for each row execute function public.reject_mutation();
create trigger health_assessment_sources_immutable
  before update or delete on public.health_assessment_sources
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
alter table public.health_assessments        enable row level security;
alter table public.health_assessment_images  enable row level security;
alter table public.health_observations       enable row level security;
alter table public.health_issues             enable row level security;
alter table public.health_recommendations    enable row level security;
alter table public.health_assessment_sources enable row level security;

create policy health_assessments_select_own
  on public.health_assessments for select
  to authenticated
  using (user_id = auth.uid());

create policy health_assessments_insert_own
  on public.health_assessments for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.plants p
      where p.id = health_assessments.plant_id and p.user_id = auth.uid()
    )
  );

create policy health_assessments_select_admin
  on public.health_assessments for select
  to authenticated
  using (public.is_admin());

-- Children authorise through the owning assessment.
do $do$
declare
  child text;
begin
  foreach child in array array[
    'health_assessment_images', 'health_observations', 'health_issues',
    'health_recommendations', 'health_assessment_sources'
  ] loop
    execute format($f$
      create policy %1$I_select_own on public.%1$I for select to authenticated
      using (exists (
        select 1 from public.health_assessments a
        where a.id = %1$I.health_assessment_id and a.user_id = auth.uid()
      ));
      create policy %1$I_insert_own on public.%1$I for insert to authenticated
      with check (exists (
        select 1 from public.health_assessments a
        where a.id = %1$I.health_assessment_id and a.user_id = auth.uid()
      ));
      create policy %1$I_select_admin on public.%1$I for select to authenticated
      using (public.is_admin());
    $f$, child);
  end loop;
end;
$do$;
