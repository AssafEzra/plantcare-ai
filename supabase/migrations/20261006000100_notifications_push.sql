-- =============================================================================
-- 0022 · Notifications: Today / Due / Evening, by email and phone push.
--
-- Two morning notifications at the user's time (07:30 for now):
--   * Today - tasks due today;
--   * Due   - open tasks past their due date, for `due_reminder_days` days after it.
-- One evening push (off by default) for today's tasks still open.
--
-- Email carries Today and Due as one message with two sections. Per-task emails
-- are gone: `daily_digest` is forced true and no longer read, and the column stays
-- only so nothing that selects it breaks.
--
-- The times are stored per user and fixed for now. They are the hook for letting
-- users choose later; the interface does not show them yet.
-- =============================================================================

alter type notification_channel add value if not exists 'PUSH';

-- --- preferences ---------------------------------------------------------------

alter table public.notification_preferences
  alter column preferred_time_local set default '07:30',
  add column due_reminder_days  smallint not null default 1,
  add column evening_enabled    boolean  not null default false,
  add column evening_time_local time     not null default '19:00',
  add constraint notification_preferences_due_days_range
    check (due_reminder_days between 0 and 3);

comment on column public.notification_preferences.preferred_time_local is
  'When the morning Today and Due notifications may be sent (local time). Fixed at 07:30 for now.';
comment on column public.notification_preferences.due_reminder_days is
  'How many days after a task''s due date it is still included in the Due notification. 0 = never.';
comment on column public.notification_preferences.evening_enabled is
  'Evening push for today''s tasks still open. Push only.';
comment on column public.notification_preferences.daily_digest is
  'Retired by migration 0022: per-task emails no longer exist. Always true, not read.';

-- Everyone moves to the new schedule: the time picker is hidden, so a time chosen
-- under the old screen would be one the user can no longer see or change.
update public.notification_preferences
   set preferred_time_local = '07:30',
       daily_digest = true;

-- --- push devices --------------------------------------------------------------

-- One row per phone or tablet that has allowed notifications. The endpoint is the
-- device's address at its push service (Google for Android, Apple for iPhone), so
-- it is unique: the same device registering again updates its row.
create table public.push_subscriptions (
  id           uuid        primary key default gen_random_uuid(),
  user_id      uuid        not null references public.profiles (id) on delete cascade,
  endpoint     text        not null,
  p256dh       text        not null,
  auth         text        not null,
  device_label text,
  platform     text        not null default 'other',
  enabled      boolean     not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  last_sent_at timestamptz,

  constraint push_subscriptions_platform_known check (platform in ('ios', 'android', 'other')),
  constraint push_subscriptions_endpoint_https check (endpoint like 'https://%')
);

create unique index push_subscriptions_endpoint on public.push_subscriptions (endpoint);
create index idx_push_subscriptions_user on public.push_subscriptions (user_id) where enabled;

create trigger push_subscriptions_set_updated_at
  before update on public.push_subscriptions
  for each row execute function public.set_updated_at();

alter table public.push_subscriptions enable row level security;

-- A user registers, pauses and removes their own devices from the app. The
-- dispatcher runs on the service client and is unaffected by these.
create policy push_subscriptions_select_own
  on public.push_subscriptions for select to authenticated
  using (user_id = auth.uid());

create policy push_subscriptions_insert_own
  on public.push_subscriptions for insert to authenticated
  with check (user_id = auth.uid());

create policy push_subscriptions_update_own
  on public.push_subscriptions for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy push_subscriptions_delete_own
  on public.push_subscriptions for delete to authenticated
  using (user_id = auth.uid());

create policy push_subscriptions_select_admin
  on public.push_subscriptions for select to authenticated
  using (public.is_admin());
