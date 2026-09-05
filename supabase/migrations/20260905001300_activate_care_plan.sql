-- =============================================================================
-- 0013 · Activating a care plan version.
--
-- Spec: FINAL_SPECIFICATION §12 (user approval creates a new version), §13
--       (tasks are derived from the *active* version), A5 (outstanding tasks)
--
-- Approving a proposal is four writes that must all happen or none:
--
--   1. the proposed version becomes ACTIVE,
--   2. the previously active version becomes SUPERSEDED,
--   3. `care_plans.active_version_id` points at the new one,
--   4. every PENDING task from the old version's rules is CANCELLED (A5).
--
-- The partial unique index `care_plan_versions_one_active` permits exactly one
-- ACTIVE version per plan, so — exactly as with knowledge publication — the
-- ordering is forced: supersede first, then activate. A failure between the two
-- would leave a plant with **no** active plan, and the scheduler reads rules from
-- the active version, so that plant would silently stop being cared for.
--
-- Step 4 is the one worth arguing about. The old version's PENDING tasks were
-- generated from rules the user has just replaced; leaving them would have the
-- plant reminded on the old schedule and the new one simultaneously. They are
-- CANCELLED rather than deleted because `care_tasks` feeds the history timeline
-- and a task that vanishes is indistinguishable from one that never existed.
-- DONE, SKIPPED and OVERDUE tasks are untouched: those are records of what
-- happened, and a new plan does not change the past.
--
-- SECURITY INVOKER, deliberately
-- ------------------------------
-- Unlike knowledge publication, everything here belongs to the calling user. RLS
-- on `care_plans`, `care_plan_versions` and `care_tasks` should apply in full,
-- and a definer function would bypass exactly the checks that make this safe.
-- =============================================================================

create or replace function public.activate_care_plan_version(
  p_version_id uuid
)
returns public.care_plan_versions
language plpgsql
security invoker
set search_path = public, pg_temp
as $fn$
declare
  v_version  public.care_plan_versions;
  v_previous uuid;
begin
  select * into v_version
    from public.care_plan_versions
   where id = p_version_id
     for update;

  if not found then
    raise exception 'care plan version % not found', p_version_id using errcode = 'no_data_found';
  end if;

  if v_version.status <> 'PROPOSED' then
    -- FINAL §12: approval is what makes a version active. A version that is
    -- already ACTIVE, SUPERSEDED or REJECTED has had its moment.
    raise exception 'a care plan version in status % cannot be activated', v_version.status
      using errcode = 'check_violation';
  end if;

  select id into v_previous
    from public.care_plan_versions
   where care_plan_id = v_version.care_plan_id
     and status = 'ACTIVE';

  -- Supersede before activating: the unique index allows only one ACTIVE row.
  if v_previous is not null then
    update public.care_plan_versions set status = 'SUPERSEDED' where id = v_previous;

    -- A5. Tasks not yet acted on came from rules that no longer apply.
    update public.care_tasks t
       set status = 'CANCELLED'
      from public.care_rules r
     where t.care_rule_id = r.id
       and r.care_plan_version_id = v_previous
       and t.status = 'PENDING';
  end if;

  update public.care_plan_versions
     set status = 'ACTIVE'
   where id = v_version.id
   returning * into v_version;

  update public.care_plans
     set active_version_id = v_version.id
   where id = v_version.care_plan_id;

  return v_version;
end;
$fn$;

revoke all on function public.activate_care_plan_version(uuid) from public;
grant execute on function public.activate_care_plan_version(uuid) to authenticated, service_role;

comment on function public.activate_care_plan_version(uuid) is
  'Approves a proposed version: supersedes the previous one, cancels its '
  'outstanding PENDING tasks (A5), and repoints care_plans.active_version_id. '
  'SECURITY INVOKER - everything here belongs to the calling user, so RLS applies.';


-- -----------------------------------------------------------------------------
-- care_tasks: CANCELLED must be reachable.
--
-- The status enum already carries it, but nothing in PR 6 exercised the path, and
-- the API-side cancel does not exist yet either. Asserting it here means the
-- function above cannot be the thing that discovers the enum is wrong.
-- -----------------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from pg_enum e
      join pg_type t on t.oid = e.enumtypid
     where t.typname = 'care_task_status' and e.enumlabel = 'CANCELLED'
  ) then
    raise exception 'care_task_status is missing CANCELLED, which A5 requires';
  end if;
end;
$$;
