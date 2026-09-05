-- =============================================================================
-- 0007 · Care plans, versions, rules, tasks and events.
--
-- Spec: DATABASE_SCHEMA "care_plans" … "care_events"
--       FINAL_SPECIFICATION §12 (care agent), §13 (rules/tasks/events)
--
-- Several plan decisions become database guarantees here rather than conventions
-- the scheduler must remember. Each is called out at its constraint.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- care_plans — exactly one per plant.
-- -----------------------------------------------------------------------------
create table public.care_plans (
  id                uuid        primary key default gen_random_uuid(),
  user_id           uuid        not null references public.profiles (id) on delete cascade,
  plant_id          uuid        not null unique references public.plants (id) on delete cascade,
  -- FK added below, once care_plan_versions exists (circular reference).
  active_version_id uuid,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create trigger care_plans_set_updated_at
  before update on public.care_plans
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- care_plan_versions
--
-- Content-immutable, status-mutable: the version legitimately moves
-- PROPOSED -> ACTIVE -> SUPERSEDED/REJECTED, while its professional content must
-- never change (FINAL §12: professional recommendation content is not directly
-- editable). source_type is the single provenance audit trail — there is no
-- separate care_plan_changes table.
-- -----------------------------------------------------------------------------
create table public.care_plan_versions (
  id                          uuid                          primary key default gen_random_uuid(),
  care_plan_id                uuid                          not null references public.care_plans (id) on delete cascade,
  version_number              integer                       not null,
  knowledge_version_id        uuid                          references public.knowledge_versions (id) on delete restrict,
  status                      care_plan_version_status      not null default 'PROPOSED',
  professional_recommendations jsonb                        not null,
  operational_preferences     jsonb,
  change_summary              text,
  source_type                 care_plan_version_source_type not null,
  created_by_user_id          uuid                          references public.profiles (id) on delete set null,
  created_at                  timestamptz                   not null default now(),

  constraint care_plan_versions_number_positive check (version_number >= 1),
  -- Any version after the first exists because something changed; recording what
  -- is the whole point of the provenance trail.
  constraint care_plan_versions_change_summary_required
    check (version_number = 1 or change_summary is not null)
);

create unique index care_plan_versions_number_key
  on public.care_plan_versions (care_plan_id, version_number);

-- At most one ACTIVE version per plan. The scheduler reads rules from the active
-- version, so two would silently double every task.
create unique index care_plan_versions_one_active
  on public.care_plan_versions (care_plan_id)
  where status = 'ACTIVE';

create index idx_care_plan_versions_plan
  on public.care_plan_versions (care_plan_id, version_number desc);

-- status is deliberately absent from the protected list.
create trigger care_plan_versions_content_immutable
  before update on public.care_plan_versions
  for each row execute function public.reject_content_mutation(
    'care_plan_id', 'version_number', 'knowledge_version_id',
    'professional_recommendations', 'source_type', 'created_by_user_id'
  );

alter table public.care_plans
  add constraint care_plans_active_version_fk
  foreign key (active_version_id) references public.care_plan_versions (id) on delete set null;

-- -----------------------------------------------------------------------------
-- care_rules — recurring logic belonging to one plan version.
-- -----------------------------------------------------------------------------
create table public.care_rules (
  id                   uuid                  primary key default gen_random_uuid(),
  care_plan_version_id uuid                  not null references public.care_plan_versions (id) on delete cascade,
  action_type          care_rule_action_type not null,
  interval_days        integer               not null,
  preferred_time_local time                  not null default '08:00',
  preferred_weekday    weekday,
  instructions         text,
  is_active            boolean               not null default true,
  created_at           timestamptz           not null default now(),

  -- interval_days always defines the recurrence period (DATABASE_SCHEMA).
  -- The upper bound rejects a model emitting nonsense like 3650.
  constraint care_rules_interval_sane check (interval_days between 1 and 365),

  -- A7 as a database guarantee. preferred_weekday only anchors *which* day a
  -- recurrence lands on; it is never an alternate recurrence mode. Anchoring a
  -- weekday to a 5-day interval is incoherent, so it is rejected rather than
  -- silently ignored by the scheduler.
  constraint care_rules_weekday_requires_weekly_multiple
    check (preferred_weekday is null or interval_days % 7 = 0)
);

create index idx_care_rules_version on public.care_rules (care_plan_version_id) where is_active;

-- -----------------------------------------------------------------------------
-- care_tasks — actionable occurrences generated from the active version's rules.
-- -----------------------------------------------------------------------------
create table public.care_tasks (
  id            uuid             primary key default gen_random_uuid(),
  user_id       uuid             not null references public.profiles (id) on delete cascade,
  plant_id      uuid             not null references public.plants (id) on delete cascade,
  care_rule_id  uuid             not null references public.care_rules (id) on delete cascade,
  due_at_utc    timestamptz      not null,
  status        care_task_status not null default 'PENDING',
  overdue_since timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz      not null default now(),

  constraint care_tasks_overdue_has_timestamp
    check (status <> 'OVERDUE' or overdue_since is not null),
  constraint care_tasks_completed_has_timestamp
    check ((status = 'DONE') = (completed_at is not null))
);

-- The materialisation invariant: at most one PENDING task per rule. Generating
-- only near-term work is a spec requirement (DATABASE_SCHEMA: "do not
-- pre-generate thousands of future tasks"), and this makes a buggy scheduler run
-- unable to violate it. A task that has gone OVERDUE is no longer PENDING, so the
-- next recurrence can still be scheduled.
create unique index care_tasks_one_pending_per_rule
  on public.care_tasks (care_rule_id)
  where status = 'PENDING';

create index idx_care_tasks_user_due on public.care_tasks (user_id, due_at_utc, status);
create index idx_care_tasks_plant on public.care_tasks (plant_id, due_at_utc desc);
create index idx_care_tasks_open
  on public.care_tasks (due_at_utc)
  where status in ('PENDING', 'OVERDUE');

-- -----------------------------------------------------------------------------
-- care_events — immutable record of what actually happened.
-- -----------------------------------------------------------------------------
create table public.care_events (
  id                    uuid            primary key default gen_random_uuid(),
  user_id               uuid            not null references public.profiles (id) on delete cascade,
  plant_id              uuid            not null references public.plants (id) on delete cascade,
  care_task_id          uuid            references public.care_tasks (id) on delete set null,
  event_type            care_event_type not null,
  event_at              timestamptz     not null default now(),
  note                  text,
  correction_of_event_id uuid           references public.care_events (id) on delete restrict,
  created_at            timestamptz     not null default now(),

  -- Only a CORRECTED event may point at the event it corrects, and it must.
  constraint care_events_correction_shape
    check ((event_type = 'CORRECTED') = (correction_of_event_id is not null))
);

-- API_CONTRACTS: "Duplicate action events are rejected." A task can be completed
-- or skipped once; the 409 the API returns is backed by this index rather than by
-- a read-then-write race in application code.
create unique index care_events_one_action_per_task
  on public.care_events (care_task_id)
  where event_type in ('DONE', 'SKIPPED') and care_task_id is not null;

create index idx_care_events_plant on public.care_events (plant_id, event_at desc);
create index idx_care_events_user on public.care_events (user_id, event_at desc);

-- Immutable: corrections create new events (FINAL §13).
create trigger care_events_immutable
  before update or delete on public.care_events
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
alter table public.care_plans          enable row level security;
alter table public.care_plan_versions  enable row level security;
alter table public.care_rules          enable row level security;
alter table public.care_tasks          enable row level security;
alter table public.care_events         enable row level security;

create policy care_plans_own
  on public.care_plans for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Versions carry no user_id; ownership is proven through the plan.
create policy care_plan_versions_select_own
  on public.care_plan_versions for select
  to authenticated
  using (
    exists (
      select 1 from public.care_plans p
      where p.id = care_plan_versions.care_plan_id and p.user_id = auth.uid()
    )
  );

create policy care_plan_versions_insert_own
  on public.care_plan_versions for insert
  to authenticated
  with check (
    exists (
      select 1 from public.care_plans p
      where p.id = care_plan_versions.care_plan_id and p.user_id = auth.uid()
    )
  );

-- UPDATE is permitted so the user can approve or reject a proposal, which is a
-- status transition. The content trigger above is what keeps that from becoming
-- an edit of the professional recommendation.
create policy care_plan_versions_update_own
  on public.care_plan_versions for update
  to authenticated
  using (
    exists (
      select 1 from public.care_plans p
      where p.id = care_plan_versions.care_plan_id and p.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.care_plans p
      where p.id = care_plan_versions.care_plan_id and p.user_id = auth.uid()
    )
  );

create policy care_rules_own
  on public.care_rules for all
  to authenticated
  using (
    exists (
      select 1
      from public.care_plan_versions v
      join public.care_plans p on p.id = v.care_plan_id
      where v.id = care_rules.care_plan_version_id and p.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.care_plan_versions v
      join public.care_plans p on p.id = v.care_plan_id
      where v.id = care_rules.care_plan_version_id and p.user_id = auth.uid()
    )
  );

create policy care_tasks_own
  on public.care_tasks for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Users may record events but never rewrite them; the trigger enforces the rest.
create policy care_events_select_own
  on public.care_events for select
  to authenticated
  using (user_id = auth.uid());

create policy care_events_insert_own
  on public.care_events for insert
  to authenticated
  with check (user_id = auth.uid());

create policy care_plans_select_admin
  on public.care_plans for select to authenticated using (public.is_admin());
create policy care_tasks_select_admin
  on public.care_tasks for select to authenticated using (public.is_admin());
create policy care_events_select_admin
  on public.care_events for select to authenticated using (public.is_admin());
