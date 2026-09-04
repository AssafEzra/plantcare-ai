-- =============================================================================
-- 0002 · Corrective: make the profiles privilege guard exempt trusted roles.
--
-- Forward fix for 20260905000100 (DEPLOYMENT_AND_OPERATIONS §11 prefers a
-- corrective migration over editing an applied one).
--
-- Two defects in the original:
--
-- 1. The exemption only recognised a `service_role` JWT claim. A direct database
--    connection — migrations, the Supabase SQL editor, operational maintenance —
--    carries no JWT, so `postgres` was blocked from changing role/is_active/
--    anonymized_at. That breaks the admin anonymisation path in FINAL §21 and
--    ordinary ops work.
--
-- 2. More fundamentally, the function was SECURITY DEFINER, under which
--    `current_user` is the function *owner*, not the caller. Any role check
--    inside it was therefore meaningless. The guard needs no elevated
--    privileges — it only inspects OLD/NEW and raises — so it becomes
--    SECURITY INVOKER and can read the real caller.
--
-- The discriminator is `rolbypassrls`: postgres, supabase_admin and service_role
-- have it; authenticated and anon do not. A role already trusted to bypass row
-- security is trusted to write privileged columns. The account holder, arriving
-- as `authenticated`, still cannot.
-- =============================================================================

create or replace function public.profiles_guard_privileged_columns()
returns trigger
language plpgsql
as $fn$
declare
  caller_is_trusted boolean;
begin
  select coalesce(bool_or(r.rolsuper or r.rolbypassrls), false)
    into caller_is_trusted
    from pg_roles r
   where r.rolname = current_user;

  if caller_is_trusted then
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

comment on function public.profiles_guard_privileged_columns() is
  'Blocks the account holder from writing role/is_active/anonymized_at. RLS gates '
  'rows, not columns, so the "update your own profile" policy alone would permit '
  'self-promotion to ADMIN (TESTING_STRATEGY §7). Deliberately SECURITY INVOKER: '
  'under SECURITY DEFINER, current_user would be the owner rather than the caller.';
