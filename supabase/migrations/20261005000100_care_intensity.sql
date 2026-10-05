-- =============================================================================
-- 0021 · Care intensity: group a user's care onto fixed weekdays.
--
-- HIGH does each task at its own optimal time, which is what the scheduler has
-- always done. MEDIUM moves every task onto two care days a week, LOW onto one.
--
-- This is a scheduling preference, not a plan change. Care plans, their rules and
-- their advice are untouched; the scheduler moves a due date onto the nearest care
-- day when it materialises a task (app/domain/rules/recurrence.py). That is why it
-- lives on profiles and plants rather than in care_plan_versions: changing it must
-- take effect at once, with no proposal to approve and no model call.
--
-- Not the excluded `care_level` (FINAL section 2): that was the user's expertise
-- (Beginner / Advanced) feeding the agent. This never reaches the agent.
-- =============================================================================

create type care_intensity as enum ('HIGH', 'MEDIUM', 'LOW');

-- Each level keeps its own days, so switching MEDIUM -> LOW -> MEDIUM does not lose
-- the two days the user picked. Defaults: Friday for LOW, Tuesday + Friday for
-- MEDIUM - three and four days apart, the most even split of a week.
alter table public.profiles
  add column care_intensity   care_intensity not null default 'HIGH',
  add column care_day_low     weekday        not null default 'FRIDAY',
  add column care_days_medium weekday[]      not null default '{TUESDAY,FRIDAY}',
  add constraint profiles_care_days_medium_two_distinct
    check (
      cardinality(care_days_medium) = 2
      and care_days_medium[1] is distinct from care_days_medium[2]
    );

comment on column public.profiles.care_intensity is
  'HIGH = each task at its optimal time; MEDIUM / LOW = tasks moved onto care days.';
comment on column public.profiles.care_day_low is
  'The one care day used when care_intensity is LOW.';
comment on column public.profiles.care_days_medium is
  'The two care days used when care_intensity is MEDIUM.';

-- Null means "follow the owner's setting", and that is the point of it being null
-- rather than a copy: a plant left alone follows every later change in Settings.
-- Only a plant the user explicitly pinned keeps its own level.
alter table public.plants
  add column care_intensity care_intensity;

comment on column public.plants.care_intensity is
  'Per-plant override of profiles.care_intensity. Null = follow the owner''s setting.';
