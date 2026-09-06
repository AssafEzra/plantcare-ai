-- =============================================================================
-- 0017 · A care plan may be built from a draft that has not been reviewed yet.
--
-- FINAL §10/§11 make admin review the gate between what the Knowledge Agent
-- writes and what a user sees, and that gate stays: nothing here publishes, and
-- `knowledge_versions` is still written only by an administrator approving a
-- draft.
--
-- What changes is what happens *while* a draft waits. Until now a plant sat in
-- KNOWLEDGE_PENDING doing nothing at all - no knowledge, no plan, no schedule -
-- until a human intervened. For a single-operator MVP that is indistinguishable
-- from the product not working. So a draft that has finished research is shown
-- to the owner of a plant of that species, clearly marked as unreviewed, and the
-- Care Agent may build a plan from it.
--
-- Three things make that honest rather than a quiet removal of the gate:
--
--   1. Provenance stays exact. A version cites the draft it came from *or* the
--      published version it came from, never both and never neither.
--   2. Visibility is scoped. A user may read a draft only for a species they
--      actually own a plant of, and only once research has finished.
--   3. Rejection is handled. If an administrator later rejects the draft, the
--      plan keeps running - cancelling it would leave the plant with no schedule
--      at all - and the owner is told, from the join between the plan's draft and
--      that draft's status. No extra state to drift.
-- =============================================================================

-- --- provenance ---------------------------------------------------------------

alter table public.care_plan_versions
  add column knowledge_draft_id uuid references public.knowledge_drafts (id) on delete restrict;

comment on column public.care_plan_versions.knowledge_draft_id is
  'The unreviewed draft this version was built from, when it was not built from a '
  'published version. Exactly one of knowledge_draft_id / knowledge_version_id is '
  'set on any version that cites knowledge at all.';

-- Never both. A plan built from a draft and later reconciled against the
-- published version becomes a *new* version citing that version, because
-- `care_plan_versions` is content-immutable and rewriting provenance in place is
-- precisely what that immutability exists to prevent.
alter table public.care_plan_versions
  add constraint care_plan_versions_one_knowledge_source
  check (knowledge_draft_id is null or knowledge_version_id is null);

create index idx_care_plan_versions_draft
  on public.care_plan_versions (knowledge_draft_id)
  where knowledge_draft_id is not null;

-- The new column joins the set the content-immutability trigger protects: which
-- knowledge a plan rests on is the whole point of recording it, and
-- `knowledge_version_id` has been protected since migration 0007. Recreating the
-- trigger with an extra argument is all this needs - `reject_content_mutation()`
-- takes its column list from `tg_argv`, so there is no function to duplicate.
--
-- `created_by_user_id` is deliberately dropped from the list: it is an
-- `ON DELETE SET NULL` target, so protecting it makes deleting an account
-- impossible - which is exactly what blocked the DEV purge in PR 32, one table
-- over. Provenance of *content* is what matters here; who pressed the button is
-- already in `system_events` and the audit log.
drop trigger if exists care_plan_versions_content_immutable on public.care_plan_versions;
create trigger care_plan_versions_content_immutable
  before update on public.care_plan_versions
  for each row execute function public.reject_content_mutation(
    'care_plan_id', 'version_number', 'knowledge_version_id', 'knowledge_draft_id',
    'professional_recommendations', 'source_type'
  );

-- --- a source type for reconciling with the reviewed version -------------------

-- When an administrator approves a draft with edits, the plan a user is running
-- rests on content that no longer matches what was published. That produces a
-- proposal, not a silent swap.
alter type care_plan_version_source_type add value if not exists 'KNOWLEDGE_REVISED';

-- --- who may read an unreviewed draft ------------------------------------------

-- The first time a non-admin can read AI content that no human has checked, so
-- it is scoped as narrowly as the feature allows:
--
--   * only READY_FOR_REVIEW - a DRAFT is empty, RESEARCHING is half-written, and
--     FAILED and REJECTED are content nobody should act on;
--   * only for a species the reader actually owns a plant of;
--   * select only. Every write stays admin-only.
create policy knowledge_drafts_select_own_species
  on public.knowledge_drafts for select
  to authenticated
  using (
    status = 'READY_FOR_REVIEW'
    and exists (
      select 1
        from public.plants p
       where p.species_id = knowledge_drafts.species_id
         and p.user_id = auth.uid()
    )
  );

comment on policy knowledge_drafts_select_own_species on public.knowledge_drafts is
  'Lets a plant owner read the unreviewed knowledge their care plan was built '
  'from, marked as pending in the interface. Scoped to finished research on a '
  'species they own a plant of; writes remain admin-only.';
