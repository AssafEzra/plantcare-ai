-- =============================================================================
-- 0012 · Publishing a Knowledge Draft.
--
-- Spec: FINAL_SPECIFICATION §10 (knowledge lifecycle), §11 (the agent never
--       publishes), §29 (admin), API_CONTRACTS "Approval creates an immutable
--       Published Knowledge Version"
--
-- Publication is six writes that must all happen or none of them:
--
--   1. the previous current version is demoted,
--   2. the new immutable version is inserted with version_number = max + 1,
--   3. its sources become knowledge_sources rows,
--   4. the draft is marked APPROVED,
--   5. every KNOWLEDGE_PENDING plant of that species becomes ACTIVE (A4),
--   6. the action is written to admin_audit_log.
--
-- Done from Python they would be six round trips with no transaction around
-- them, and the partial unique index on (species_id, language) where is_current
-- makes the ordering load-bearing: demote-then-insert is the only sequence the
-- index permits, and a crash between the two would leave a species with **no**
-- current version — every plant of that species suddenly unable to find its
-- knowledge. One function, one transaction, no window.
--
-- SECURITY DEFINER, guarded by is_admin()
-- ---------------------------------------
-- The fan-out in step 5 updates *other users'* plants, which no admin JWT can do
-- through RLS and which is exactly right: an administrator approving a draft has
-- no business being able to write to a user's plant row in general. The privilege
-- is granted to this one operation rather than to the person, and the first thing
-- the function does is check that the caller really is an administrator — because
-- SECURITY DEFINER means the policies would otherwise not be consulted at all.
-- =============================================================================

create or replace function public.publish_knowledge_draft(
  p_draft_id   uuid,
  p_admin_note text default null
)
returns public.knowledge_versions
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_draft     public.knowledge_drafts;
  v_version   public.knowledge_versions;
  v_number    integer;
  v_source    jsonb;
  v_activated integer := 0;
begin
  if not public.is_admin() then
    raise exception 'admin role required' using errcode = 'insufficient_privilege';
  end if;

  -- Locked for the duration: two administrators approving the same draft at the
  -- same moment would otherwise both read READY_FOR_REVIEW and both publish.
  select * into v_draft
    from public.knowledge_drafts
   where id = p_draft_id
     for update;

  if not found then
    raise exception 'knowledge draft % not found', p_draft_id using errcode = 'no_data_found';
  end if;

  -- FINAL §11: only a draft an administrator has actually reviewed may be
  -- approved. This mirrors is_publishable() in domain/rules/knowledge_lifecycle.py
  -- so the rule holds even when something other than that workflow calls in.
  if v_draft.status <> 'READY_FOR_REVIEW' then
    raise exception 'a draft in status % cannot be published', v_draft.status
      using errcode = 'check_violation';
  end if;

  if v_draft.content is null or v_draft.content -> 'sections' is null then
    raise exception 'the draft has no researched content to publish'
      using errcode = 'check_violation';
  end if;

  -- Dense per species and language, matching knowledge_versions_number_key.
  select coalesce(max(version_number), 0) + 1 into v_number
    from public.knowledge_versions
   where species_id = v_draft.species_id
     and language   = v_draft.language;

  -- Demote first. The partial unique index allows exactly one current row, so
  -- inserting before demoting would violate it.
  update public.knowledge_versions
     set is_current = false
   where species_id = v_draft.species_id
     and language   = v_draft.language
     and is_current;

  insert into public.knowledge_versions (
    species_id, language, version_number, content, source_summary, is_current, published_by
  )
  values (
    v_draft.species_id,
    v_draft.language,
    v_number,
    -- Only the sections. Provenance moves to knowledge_sources, where each row
    -- carries a class the CHECK constraints police; leaving a second copy inside
    -- the content blob would let the two disagree with nothing to catch it.
    v_draft.content -> 'sections',
    jsonb_build_object(
      'total',      jsonb_array_length(coalesce(v_draft.content -> 'sources', '[]'::jsonb)),
      'approved',   (
        select count(*) from jsonb_array_elements(coalesce(v_draft.content -> 'sources', '[]'::jsonb)) s
         where s ->> 'source_class' = 'APPROVED'
      ),
      'unapproved', (
        select count(*) from jsonb_array_elements(coalesce(v_draft.content -> 'sources', '[]'::jsonb)) s
         where s ->> 'source_class' = 'EXTERNAL_UNAPPROVED'
      ),
      'unverified', (
        select count(*) from jsonb_array_elements(coalesce(v_draft.content -> 'sources', '[]'::jsonb)) s
         where s ->> 'source_class' = 'AI_GENERATED_REQUIRES_VERIFICATION'
      )
    ),
    true,
    auth.uid()
  )
  returning * into v_version;

  -- Provenance. The classes were decided by source_verification.py having
  -- actually fetched each URL; the CHECK constraints on knowledge_sources will
  -- refuse anything inconsistent, which is the point of writing them here rather
  -- than trusting the blob.
  for v_source in
    select * from jsonb_array_elements(coalesce(v_draft.content -> 'sources', '[]'::jsonb))
  loop
    insert into public.knowledge_sources (
      knowledge_version_id, approved_source_id, source_class,
      title, url, publisher, retrieved_at, notes
    )
    values (
      v_version.id,
      nullif(v_source ->> 'approved_source_id', '')::uuid,
      (v_source ->> 'source_class')::knowledge_source_class,
      v_source ->> 'title',
      v_source ->> 'url',
      v_source ->> 'publisher',
      -- The draft was written when research ran; that is when the page was read.
      v_draft.updated_at,
      v_source ->> 'notes'
    );
  end loop;

  update public.knowledge_drafts
     set status     = 'APPROVED',
         admin_note = coalesce(p_admin_note, admin_note)
   where id = v_draft.id;

  -- A4: the fan-out. Plants have been waiting in KNOWLEDGE_PENDING for exactly
  -- this. Restricted to that status, so an ARCHIVED plant is not silently revived
  -- and an ACTIVE one (A21 re-identification) is not disturbed.
  with released as (
    update public.plants
       set status = 'ACTIVE'
     where species_id = v_draft.species_id
       and status = 'KNOWLEDGE_PENDING'
    returning id
  )
  select count(*) into v_activated from released;

  insert into public.admin_audit_log (admin_user_id, action, target_table, target_id, payload)
  values (
    auth.uid(),
    'knowledge.publish',
    'knowledge_versions',
    v_version.id,
    jsonb_build_object(
      'draft_id',        v_draft.id,
      'species_id',      v_draft.species_id,
      'language',        v_draft.language,
      'version_number',  v_number,
      'plants_released', v_activated,
      'admin_note',      p_admin_note
    )
  );

  return v_version;
end;
$fn$;

revoke all on function public.publish_knowledge_draft(uuid, text) from public;
grant execute on function public.publish_knowledge_draft(uuid, text) to authenticated, service_role;

comment on function public.publish_knowledge_draft(uuid, text) is
  'Publishes a reviewed draft as an immutable version and releases the plants '
  'waiting on it. Admin-only, checked inside the function because SECURITY '
  'DEFINER bypasses RLS.';


-- -----------------------------------------------------------------------------
-- Rejecting a draft (A17).
--
-- Separate from publication because it is the opposite outcome, but it shares the
-- property that matters: it must leave the species retriable. Plants stay in
-- KNOWLEDGE_PENDING and nothing about them changes — a rejection is a verdict on
-- the draft, not on the plants, and stranding them would be the failure A17
-- exists to prevent.
-- -----------------------------------------------------------------------------
create or replace function public.reject_knowledge_draft(
  p_draft_id   uuid,
  p_admin_note text
)
returns public.knowledge_drafts
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_draft public.knowledge_drafts;
begin
  if not public.is_admin() then
    raise exception 'admin role required' using errcode = 'insufficient_privilege';
  end if;

  if p_admin_note is null or length(btrim(p_admin_note)) = 0 then
    -- A rejection with no reason cannot be acted on: the retry has nothing to
    -- address, and the audit entry records that someone said no and nothing else.
    raise exception 'a rejection must carry a reason' using errcode = 'check_violation';
  end if;

  select * into v_draft from public.knowledge_drafts where id = p_draft_id for update;
  if not found then
    raise exception 'knowledge draft % not found', p_draft_id using errcode = 'no_data_found';
  end if;

  if v_draft.status <> 'READY_FOR_REVIEW' then
    raise exception 'a draft in status % cannot be rejected', v_draft.status
      using errcode = 'check_violation';
  end if;

  update public.knowledge_drafts
     set status = 'REJECTED', admin_note = p_admin_note
   where id = v_draft.id
   returning * into v_draft;

  insert into public.admin_audit_log (admin_user_id, action, target_table, target_id, payload)
  values (
    auth.uid(), 'knowledge.reject', 'knowledge_drafts', v_draft.id,
    jsonb_build_object('species_id', v_draft.species_id, 'admin_note', p_admin_note)
  );

  return v_draft;
end;
$fn$;

revoke all on function public.reject_knowledge_draft(uuid, text) from public;
grant execute on function public.reject_knowledge_draft(uuid, text) to authenticated, service_role;


-- -----------------------------------------------------------------------------
-- admin_audit_log: administrators write their own entries.
--
-- The table was created with an admin-read policy and no INSERT policy, on the
-- assumption that only the service role would write it. The two functions above
-- are SECURITY DEFINER and so bypass RLS, but every *other* consequential admin
-- action in PR 15 — disabling a source, actioning a report — is an ordinary write
-- through the administrator's own client, and would have failed exactly as
-- agent_requests did in PR 13.
--
-- No UPDATE and no DELETE policy, deliberately: the immutability trigger already
-- refuses both, and an audit trail an administrator can edit is not an audit
-- trail. INSERT is restricted to entries the administrator attributes to
-- themselves.
-- -----------------------------------------------------------------------------
create policy admin_audit_log_insert_admin
  on public.admin_audit_log for insert
  to authenticated
  with check (public.is_admin() and admin_user_id = auth.uid());
