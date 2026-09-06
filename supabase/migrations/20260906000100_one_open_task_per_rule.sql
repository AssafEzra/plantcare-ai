-- =============================================================================
-- 0016 · The materialisation invariant covers OVERDUE too.
--
-- `care_tasks_one_pending_per_rule` (migration 0007) constrained PENDING alone.
-- Its own comment described the intent as "at most one PENDING task per rule …
-- so a buggy scheduler run cannot violate it", and reasoned that "a task that has
-- gone OVERDUE is no longer PENDING, so the next recurrence can still be
-- scheduled".
--
-- That reasoning is wrong, and PR 32 made it visible by being the first change to
-- actually run the tick. A rule whose task has gone OVERDUE has no PENDING row,
-- so `materialise` schedules it again — and since a rule with no care events
-- computes the same due date every time, the new row is a *copy* of the overdue
-- one rather than a following occurrence. Every tick added another. One DEV
-- account had four rules and eight identical overdue tasks after two runs.
--
-- FINAL §13 is explicit: "Do not create an infinite backlog." The next recurrence
-- is not lost by waiting — an overdue task nobody is going to do becomes a MISSED
-- event and is CANCELLED (A9), and *that* is what frees the rule to be scheduled
-- again.
--
-- Forward fix rather than an edit to 0007 (DEPLOYMENT_AND_OPERATIONS §6).
-- =============================================================================

-- Existing duplicates have to go before a unique index will build. Keep the
-- oldest open task per rule: it is the one whose due date the user has been
-- looking at, and the one any MISSED event should be written against.
with ranked as (
  select id,
         row_number() over (
           partition by care_rule_id
           order by due_at_utc, created_at, id
         ) as position
    from public.care_tasks
   where status in ('PENDING', 'OVERDUE')
)
delete from public.care_tasks t
 using ranked
 where t.id = ranked.id
   and ranked.position > 1
   -- A task someone has already acted on is not a duplicate. This only ever
   -- matches open rows, but the join is cheap insurance.
   and not exists (
     select 1 from public.care_events e where e.care_task_id = t.id
   );

drop index if exists public.care_tasks_one_pending_per_rule;

create unique index care_tasks_one_open_per_rule
  on public.care_tasks (care_rule_id)
  where status in ('PENDING', 'OVERDUE');

comment on index public.care_tasks_one_open_per_rule is
  'At most one outstanding task per care rule. Replaces the PENDING-only index, '
  'under which a task going OVERDUE freed its rule and every scheduler tick '
  'materialised another copy (FINAL §13: "do not create an infinite backlog").';
