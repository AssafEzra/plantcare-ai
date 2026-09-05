-- =============================================================================
-- 0015 · Anonymising an account (FINAL §21).
--
--   "Do not physically delete the account record. Instead: anonymize
--    identifying/user-related details, disable access, preserve anonymized
--    history/data where required, restrict access to the anonymized account
--    data to Admin."
--
-- Four things that must happen together, and the reason this is one function:
--
--   1. identifying fields are cleared,
--   2. access is disabled,
--   3. the history stays,
--   4. the action is audited.
--
-- Half of that is worse than none. An account with its email cleared but access
-- still enabled is a user locked out of a login they can still perform; an
-- account disabled but not anonymised is a deletion request that did nothing.
--
-- What is deliberately *not* touched
-- ----------------------------------
-- Plants, care history, health assessments and knowledge contributions all
-- survive. §21 says to preserve anonymised history, and there are good reasons
-- beyond the spec: a published knowledge version cannot be deleted at all, and
-- care events are immutable by trigger. What changes is that nothing in the
-- account identifies a person any more.
--
-- The `auth.users` row is left to the caller. This function owns the public
-- schema; revoking the credential is Supabase's own admin API, and doing it here
-- would put a second, partial copy of that logic in SQL.
--
-- SECURITY DEFINER, guarded by is_admin()
-- ---------------------------------------
-- It writes another user's profile, which no JWT can do through RLS — correctly,
-- since an administrator should not be able to edit user rows in general. The
-- privilege belongs to this one operation.
-- =============================================================================

create or replace function public.anonymize_account(
  p_user_id uuid,
  p_reason  text default null
)
returns public.profiles
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_profile public.profiles;
  v_plants  integer;
begin
  if not public.is_admin() then
    raise exception 'admin role required' using errcode = 'insufficient_privilege';
  end if;

  if p_user_id = auth.uid() then
    -- An administrator anonymising themselves would revoke the role needed to
    -- undo it, and leave the system with one fewer administrator by accident.
    raise exception 'an administrator cannot anonymise their own account'
      using errcode = 'check_violation';
  end if;

  select * into v_profile from public.profiles where id = p_user_id for update;
  if not found then
    raise exception 'profile % not found', p_user_id using errcode = 'no_data_found';
  end if;

  if v_profile.anonymized_at is not null then
    -- Already done. Returning the row rather than raising makes the operation
    -- idempotent, which matters for something executed by hand from a ticket.
    return v_profile;
  end if;

  select count(*) into v_plants from public.plants where user_id = p_user_id;

  update public.profiles
     set email         = null,
         display_name  = null,
         is_active     = false,
         anonymized_at = now()
   where id = p_user_id
   returning * into v_profile;

  -- The plants keep their history and their species; only the names a person
  -- chose are identifying, and those are what a user would have typed.
  update public.plants
     set name  = null,
         notes = null
   where user_id = p_user_id;

  insert into public.admin_audit_log (admin_user_id, action, target_table, target_id, payload)
  values (
    auth.uid(),
    'account.anonymize',
    'profiles',
    p_user_id,
    jsonb_build_object(
      'reason', p_reason,
      'plants_retained', v_plants,
      -- Deliberately no email and no display name: an audit entry that recorded
      -- what was erased would preserve exactly the data the operation removes.
      'note', 'identifying fields cleared; history retained'
    )
  );

  return v_profile;
end;
$fn$;

revoke all on function public.anonymize_account(uuid, text) from public;
grant execute on function public.anonymize_account(uuid, text) to authenticated, service_role;

comment on function public.anonymize_account(uuid, text) is
  'FINAL §21: clears identifying fields, disables access, keeps the history, and '
  'audits the action - in one transaction, because half of it is worse than none. '
  'The audit entry deliberately records no identifying data.';


-- No policy needed for admin reads: `profiles_select_admin` already exists from
-- migration 0001. I wrote one here on the assumption it was missing, the way it
-- had been missing on `agent_requests` and `admin_audit_log`, and the database
-- refused the duplicate. The assumption was wrong and the note is kept so the
-- next person does not repeat it.
