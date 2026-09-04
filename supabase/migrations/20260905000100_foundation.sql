-- =============================================================================
-- 0001 · Foundation: extensions, enums, profiles, notification preferences,
--        shared trigger functions, the is_admin() helper, and signup wiring.
--
-- Spec: DATABASE_SCHEMA "Lifecycle enums", "profiles", "notification_preferences"
--       FINAL_SPECIFICATION §21 (anonymisation), §22 (auth/roles), §26 (RLS)
--
-- Every enum here is deliberately minimal: ALTER TYPE ... ADD VALUE is cheap,
-- removing or renaming a value is not.
-- =============================================================================

create extension if not exists pgcrypto;

-- -----------------------------------------------------------------------------
-- Enums (DATABASE_SCHEMA "Lifecycle enums")
-- -----------------------------------------------------------------------------
create type user_role as enum ('USER', 'ADMIN');

create type plant_status as enum (
  'PENDING_IDENTIFICATION', 'IDENTIFIED', 'KNOWLEDGE_PENDING', 'ACTIVE', 'ARCHIVED'
);

create type identification_status as enum ('SUCCESS', 'NEEDS_MORE_INFORMATION', 'FAILED');
create type identification_method as enum ('AI', 'USER_CONFIRMED', 'USER_CORRECTED');
create type confidence_level as enum ('HIGH', 'MEDIUM', 'LOW');

create type knowledge_draft_status as enum (
  'DRAFT', 'RESEARCHING', 'READY_FOR_REVIEW', 'REJECTED', 'FAILED', 'APPROVED'
);
create type knowledge_source_class as enum (
  'APPROVED', 'EXTERNAL_UNAPPROVED', 'AI_GENERATED_REQUIRES_VERIFICATION'
);

create type care_plan_version_status as enum ('PROPOSED', 'ACTIVE', 'SUPERSEDED', 'REJECTED');
create type care_plan_version_source_type as enum (
  'INITIAL_PLAN', 'OPERATIONAL_ADJUSTMENT', 'ENVIRONMENT_CHANGE',
  'HEALTH_DRIVEN', 'RE_IDENTIFICATION'
);

-- NEW (A19). Recurring care actions a Care Rule may schedule. Derived from the
-- FINAL §10 Knowledge sections and the care-plan wireframe; MISTING and ROTATING
-- follow from the humidity_percent and light_direction environment fields.
create type care_rule_action_type as enum (
  'WATERING', 'FERTILIZING', 'REPOTTING', 'PRUNING', 'MISTING', 'ROTATING', 'INSPECTION'
);

create type care_task_status as enum ('PENDING', 'DONE', 'SKIPPED', 'OVERDUE', 'CANCELLED');
create type care_event_type as enum ('DONE', 'SKIPPED', 'MISSED', 'CORRECTED');

create type health_status as enum ('HEALTHY', 'NEEDS_ATTENTION', 'CRITICAL', 'UNKNOWN');
create type health_trend as enum ('IMPROVING', 'WORSENING', 'STABLE', 'UNABLE_TO_DETERMINE');

create type agent_type as enum ('IDENTIFICATION', 'KNOWLEDGE', 'CARE', 'HEALTH');
create type agent_request_status as enum (
  'QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'CANCELLED'
);

create type notification_channel as enum ('EMAIL');
create type notification_delivery_status as enum ('QUEUED', 'SENT', 'FAILED', 'SKIPPED');

-- NEW (A22). Timeline entries with no dedicated table of their own. Deliberately
-- excludes care events, health checks, identifications and care plan versions:
-- those live in their own tables and the Plant History timeline merges them.
create type system_event_type as enum (
  'PLANT_CREATED', 'PLANT_ARCHIVED', 'PLANT_RESTORED', 'PLANT_RENAMED',
  'ENVIRONMENT_CHANGED', 'MAIN_IMAGE_CHANGED',
  'REPOTTED', 'MOVED', 'PRUNED', 'CUSTOM_NOTE'
);

create type image_context_type as enum ('gallery', 'identification', 'health');

create type location_type as enum ('INDOOR', 'OUTDOOR', 'BALCONY', 'GREENHOUSE');
create type light_level as enum ('LOW', 'MEDIUM', 'BRIGHT', 'DIRECT_SUN');
create type light_direction as enum ('NORTH', 'SOUTH', 'EAST', 'WEST', 'UNKNOWN');
create type weekday as enum (
  'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'
);

-- -----------------------------------------------------------------------------
-- Shared trigger functions
-- -----------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $fn$
begin
  new.updated_at = now();
  return new;
end;
$fn$;

-- Row-immutability for append-only tables: knowledge_versions, care_events,
-- health_assessments, system_events (FINAL §1.5 "preserve history").
create or replace function public.reject_mutation()
returns trigger
language plpgsql
as $fn$
begin
  raise exception
    'Table % is append-only; % is not permitted. Corrections must create a new row.',
    tg_table_name, tg_op
    using errcode = 'restrict_violation';
end;
$fn$;

-- Content-immutability with a mutable status column. Used by care_plan_versions,
-- whose status legitimately moves PROPOSED -> ACTIVE -> SUPERSEDED/REJECTED while
-- its professional content must never change (FINAL §12).
-- Protected column names are passed as trigger arguments.
create or replace function public.reject_content_mutation()
returns trigger
language plpgsql
as $fn$
declare
  col     text;
  old_val text;
  new_val text;
begin
  foreach col in array tg_argv loop
    execute format('select ($1).%I::text', col) into old_val using old;
    execute format('select ($1).%I::text', col) into new_val using new;
    if old_val is distinct from new_val then
      raise exception
        'Column %.% is immutable once written; create a new version instead.',
        tg_table_name, col
        using errcode = 'restrict_violation';
    end if;
  end loop;
  return new;
end;
$fn$;

-- -----------------------------------------------------------------------------
-- profiles (DATABASE_SCHEMA "profiles")
--
-- care_level is deliberately absent: excluded from MVP per FINAL §2 and §36.
-- Do not reintroduce it without updating that decision.
-- -----------------------------------------------------------------------------
create table public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  email         text,
  display_name  text,
  role          user_role   not null default 'USER',
  timezone      text        not null default 'Asia/Jerusalem',
  locale        text        not null default 'he',
  is_active     boolean     not null default true,
  anonymized_at timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint profiles_timezone_not_blank check (length(trim(timezone)) > 0)
);

comment on table public.profiles is
  'One row per auth.users row, created by the on_auth_user_created trigger.';
comment on column public.profiles.anonymized_at is
  'Set when the account is anonymised. Accounts are never physically deleted (FINAL §21).';

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- notification_preferences (DATABASE_SCHEMA "notification_preferences")
--
-- Created here rather than alongside the other notification tables because the
-- signup trigger below populates it: a user must never exist without preferences
-- (A27). GET /v1/notification-preferences would otherwise be undefined for a new
-- account, and the scheduler tick would have no row to read.
-- -----------------------------------------------------------------------------
create table public.notification_preferences (
  user_id              uuid primary key references public.profiles (id) on delete cascade,
  email_enabled        boolean     not null default true,
  preferred_time_local time        not null default '08:00',
  daily_digest         boolean     not null default true,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create trigger notification_preferences_set_updated_at
  before update on public.notification_preferences
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- is_admin()
--
-- SECURITY DEFINER is required, not a convenience: an RLS policy on profiles that
-- reads profiles.role would recurse infinitely. Defining it here lets every admin
-- policy in later migrations call is_admin() safely.
-- -----------------------------------------------------------------------------
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $fn$
  select exists (
    select 1
    from public.profiles p
    where p.id = auth.uid()
      and p.role = 'ADMIN'
      and p.is_active
      and p.anonymized_at is null
  );
$fn$;

revoke all on function public.is_admin() from public;
grant execute on function public.is_admin() to authenticated, service_role;

-- -----------------------------------------------------------------------------
-- Signup wiring: every new auth user gets a profile AND notification preferences.
-- -----------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    new.email,
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'display_name', '')), '')
  )
  on conflict (id) do nothing;

  -- A27: defaults match the Settings wireframe (email on, 08:00, digest on).
  insert into public.notification_preferences (user_id)
  values (new.id)
  on conflict (user_id) do nothing;

  return new;
end;
$fn$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- -----------------------------------------------------------------------------
-- Privileged-column guard
--
-- TESTING_STRATEGY §7 requires that a client-supplied role cannot grant admin
-- access. RLS policies gate rows, not columns, so a plain "users update their own
-- profile" policy would happily let a user set role = 'ADMIN'. This closes that.
-- -----------------------------------------------------------------------------
create or replace function public.profiles_guard_privileged_columns()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  jwt_role text;
begin
  -- service_role performs administrative writes server-side and is trusted here.
  jwt_role := coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
    ''
  );
  if jwt_role = 'service_role' then
    return new;
  end if;

  if new.role is distinct from old.role then
    raise exception 'role cannot be changed by the account holder'
      using errcode = 'insufficient_privilege';
  end if;

  if new.anonymized_at is distinct from old.anonymized_at then
    raise exception 'anonymized_at is set by administrators only'
      using errcode = 'insufficient_privilege';
  end if;

  if new.is_active is distinct from old.is_active then
    raise exception 'is_active is set by administrators only'
      using errcode = 'insufficient_privilege';
  end if;

  if new.id is distinct from old.id then
    raise exception 'profile id is immutable'
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$fn$;

create trigger profiles_guard_privileged_columns
  before update on public.profiles
  for each row execute function public.profiles_guard_privileged_columns();

-- -----------------------------------------------------------------------------
-- Row Level Security
--
-- FINAL §26 / DATABASE_SCHEMA "RLS model": RLS is the real security boundary.
-- Python checks are not sufficient and must never be the only gate.
-- -----------------------------------------------------------------------------
alter table public.profiles                 enable row level security;
alter table public.notification_preferences enable row level security;

-- profiles --------------------------------------------------------------------
create policy profiles_select_own
  on public.profiles for select
  to authenticated
  using (id = auth.uid());

create policy profiles_select_admin
  on public.profiles for select
  to authenticated
  using (public.is_admin());

create policy profiles_update_own
  on public.profiles for update
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

create policy profiles_update_admin
  on public.profiles for update
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- No INSERT policy: rows are created solely by the signup trigger.
-- No DELETE policy: accounts are anonymised, never deleted (FINAL §21).

-- notification_preferences ----------------------------------------------------
create policy notification_preferences_select_own
  on public.notification_preferences for select
  to authenticated
  using (user_id = auth.uid());

create policy notification_preferences_update_own
  on public.notification_preferences for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy notification_preferences_select_admin
  on public.notification_preferences for select
  to authenticated
  using (public.is_admin());

-- No INSERT policy: created by the signup trigger.
-- No DELETE policy: rows cascade with the profile.
