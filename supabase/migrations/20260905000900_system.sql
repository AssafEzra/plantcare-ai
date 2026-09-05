-- =============================================================================
-- 0009 · AI infrastructure, notifications, system history and admin audit.
--        Closes the forward-declared foreign keys from earlier migrations.
--
-- Spec: DATABASE_SCHEMA "agent_requests", "agent_executions",
--       "notification_deliveries", "system_events"
--       FINAL_SPECIFICATION §23 (AI architecture), §14 (notifications), §19, §29
-- =============================================================================

-- -----------------------------------------------------------------------------
-- agent_requests — one row per user-visible AI operation, polled by the UI.
-- -----------------------------------------------------------------------------
create table public.agent_requests (
  id              uuid                 primary key default gen_random_uuid(),
  user_id         uuid                 not null references public.profiles (id) on delete cascade,
  plant_id        uuid                 references public.plants (id) on delete cascade,
  agent_type      agent_type           not null,
  status          agent_request_status not null default 'QUEUED',
  stage           text,
  idempotency_key text,
  -- A24: the hash of the request body, so a repeated key with a *different*
  -- payload can be told apart from a genuine retry and answered with 409.
  request_fingerprint text,
  input_summary   jsonb,
  output_summary  jsonb,
  error_code      text,
  created_at      timestamptz          not null default now(),
  updated_at      timestamptz          not null default now(),

  constraint agent_requests_stage_known
    check (stage is null or stage in (
      'IMAGES_RECEIVED', 'CONTEXT_LOADED', 'ANALYZING', 'PREPARING_RESULT', 'COMPLETE'
    ))
);

-- Idempotency is scoped per user: two users may legitimately send the same key.
create unique index agent_requests_idempotency_key
  on public.agent_requests (user_id, idempotency_key)
  where idempotency_key is not null;

create index idx_agent_requests_status on public.agent_requests (status, created_at);
create index idx_agent_requests_user on public.agent_requests (user_id, created_at desc);

create trigger agent_requests_set_updated_at
  before update on public.agent_requests
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- agent_executions — per-attempt telemetry behind a request.
--
-- FINAL §23: "Do not store chain-of-thought." The column list is deliberately
-- closed and carries no free-text field for model reasoning. raw prompt and
-- response bodies are likewise absent: error_message exists for a provider's
-- error string, not for transcripts.
-- -----------------------------------------------------------------------------
create table public.agent_executions (
  id               uuid                 primary key default gen_random_uuid(),
  agent_request_id uuid                 not null references public.agent_requests (id) on delete cascade,
  agent_type       agent_type           not null,
  model            text                 not null,
  model_version    text,
  prompt_version   text                 not null,
  status           agent_request_status not null,
  attempt          smallint             not null default 1,
  started_at       timestamptz          not null default now(),
  completed_at     timestamptz,
  input_tokens     integer,
  output_tokens    integer,
  estimated_cost   numeric(12, 6),
  latency_ms       integer,
  error_code       text,
  error_message    text,
  created_at       timestamptz          not null default now(),

  -- FINAL §23 caps structured-output retries at 2, so a request can produce at
  -- most three attempts. A higher number means the retry ceiling was bypassed.
  constraint agent_executions_attempt_within_retry_budget check (attempt between 1 and 3),
  constraint agent_executions_tokens_non_negative
    check (coalesce(input_tokens, 0) >= 0 and coalesce(output_tokens, 0) >= 0)
);

comment on table public.agent_executions is
  'Chain-of-thought is never stored (FINAL §23). There is intentionally no column '
  'for model reasoning, raw prompts or raw responses.';

create index idx_agent_executions_agent on public.agent_executions (agent_type, created_at desc);
create index idx_agent_executions_request on public.agent_executions (agent_request_id, attempt);
create index idx_agent_executions_failures
  on public.agent_executions (created_at desc)
  where status = 'FAILED';

-- Close the forward references declared in earlier migrations.
alter table public.identifications
  add constraint identifications_agent_request_fk
  foreign key (agent_request_id) references public.agent_requests (id) on delete set null;

alter table public.knowledge_drafts
  add constraint knowledge_drafts_research_request_fk
  foreign key (research_request_id) references public.agent_requests (id) on delete set null;

alter table public.health_assessments
  add constraint health_assessments_agent_request_fk
  foreign key (agent_request_id) references public.agent_requests (id) on delete set null;

-- -----------------------------------------------------------------------------
-- notification_deliveries
-- -----------------------------------------------------------------------------
create table public.notification_deliveries (
  id                  uuid                        primary key default gen_random_uuid(),
  user_id             uuid                        not null references public.profiles (id) on delete cascade,
  care_task_id        uuid                        references public.care_tasks (id) on delete set null,
  channel             notification_channel        not null default 'EMAIL',
  status              notification_delivery_status not null default 'QUEUED',
  -- A12: DATABASE_SCHEMA mandates duplicate-send prevention but defined no column
  -- for it. Format is {scope}:{identifier}:{local_date}, e.g.
  -- "digest:<user_id>:2026-09-05" or "task:<care_task_id>:reminder". The date
  -- component is the user's LOCAL date, so changing timezone cannot produce two
  -- sends on one local day.
  dedupe_key          text                        not null,
  scheduled_at        timestamptz                 not null default now(),
  sent_at             timestamptz,
  provider_message_id text,
  error_message       text,
  created_at          timestamptz                 not null default now(),

  constraint notification_deliveries_sent_has_timestamp
    check (status <> 'SENT' or sent_at is not null)
);

-- The duplicate-send guarantee. A second attempt fails on insert, before any
-- provider call, so a re-run of the scheduler tick cannot double-send.
create unique index notification_deliveries_dedupe_key on public.notification_deliveries (dedupe_key);

create index idx_notification_deliveries_schedule
  on public.notification_deliveries (status, scheduled_at);
create index idx_notification_deliveries_user
  on public.notification_deliveries (user_id, created_at desc);

-- -----------------------------------------------------------------------------
-- system_events — the generic half of Plant History.
-- -----------------------------------------------------------------------------
create table public.system_events (
  id         uuid              primary key default gen_random_uuid(),
  user_id    uuid              references public.profiles (id) on delete cascade,
  plant_id   uuid              references public.plants (id) on delete cascade,
  event_type system_event_type not null,
  payload    jsonb,
  created_at timestamptz       not null default now()
);

comment on table public.system_events is
  'Immutable. Holds only timeline entries with no dedicated table of their own; '
  'care events, health checks, identifications and care plan versions are merged '
  'in from their own tables by the Plant History view (FINAL §19).';

create index idx_system_events_plant on public.system_events (plant_id, created_at desc);
create index idx_system_events_user on public.system_events (user_id, created_at desc);
create index idx_system_events_type on public.system_events (event_type, created_at desc);

create trigger system_events_immutable
  before update or delete on public.system_events
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- admin_audit_log — A12. FINAL §29 requires consequential admin actions to be
-- audited; no table was defined for it.
-- -----------------------------------------------------------------------------
create table public.admin_audit_log (
  id            uuid        primary key default gen_random_uuid(),
  admin_user_id uuid        references public.profiles (id) on delete set null,
  action        text        not null,
  target_table  text,
  target_id     uuid,
  payload       jsonb,
  created_at    timestamptz not null default now(),

  constraint admin_audit_log_action_not_blank check (length(btrim(action)) > 0)
);

comment on column public.admin_audit_log.action is
  'Free text, deliberately not an enum: an enum would force a migration for every '
  'new administrative action, and an audit log must never block a feature.';

create index idx_admin_audit_log_created on public.admin_audit_log (created_at desc);
create index idx_admin_audit_log_admin on public.admin_audit_log (admin_user_id, created_at desc);

-- Append-only, including for administrators: an audit trail an admin can edit is
-- not an audit trail.
create trigger admin_audit_log_immutable
  before update or delete on public.admin_audit_log
  for each row execute function public.reject_mutation();

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
alter table public.agent_requests          enable row level security;
alter table public.agent_executions        enable row level security;
alter table public.notification_deliveries enable row level security;
alter table public.system_events           enable row level security;
alter table public.admin_audit_log         enable row level security;

-- DATABASE_SCHEMA: "AI monitoring is Admin-only except minimal request status for
-- the request owner."
create policy agent_requests_select_own
  on public.agent_requests for select
  to authenticated
  using (user_id = auth.uid());

create policy agent_requests_admin_all
  on public.agent_requests for all
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- Executions carry model, cost and prompt-version detail: admin-only, and
-- read-only even for admins, since they are written by the gateway service role.
create policy agent_executions_select_admin
  on public.agent_executions for select
  to authenticated
  using (public.is_admin());

create policy notification_deliveries_select_own
  on public.notification_deliveries for select
  to authenticated
  using (user_id = auth.uid());

create policy notification_deliveries_select_admin
  on public.notification_deliveries for select
  to authenticated
  using (public.is_admin());

create policy system_events_select_own
  on public.system_events for select
  to authenticated
  using (user_id = auth.uid());

create policy system_events_insert_own
  on public.system_events for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and (
      plant_id is null
      or exists (
        select 1 from public.plants p
        where p.id = system_events.plant_id and p.user_id = auth.uid()
      )
    )
  );

create policy system_events_select_admin
  on public.system_events for select
  to authenticated
  using (public.is_admin());

-- Admins read the audit log; nobody writes it through a user JWT. Writes come
-- from the service role, which bypasses RLS.
create policy admin_audit_log_select_admin
  on public.admin_audit_log for select
  to authenticated
  using (public.is_admin());
