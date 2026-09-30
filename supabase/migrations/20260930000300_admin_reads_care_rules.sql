-- =============================================================================
-- 0020 · Let an administrator read the care rules they are already looking at.
--
-- "View as user" (FINAL section 29) is read-only and audited, and it works by every
-- statement running through the administrator's own client. That means each table it
-- touches needs a policy admitting an administrator, and six of them have one:
--
--     plants, care_tasks, care_plans, plant_images, health_assessments, system_events
--
-- `care_rules` and `care_plan_versions` do not. They were written with `_own` alone
-- and the admin half was never added, so the mode showed an administrator a plant
-- with no care plan at all - and, because `scheduler.decorate_tasks` reads
-- `care_rules` to name an action, a list of tasks all reading "טיפול" instead of
-- watering, inspection and the rest.
--
-- Found while testing the React panel: the plant dashboard rendered "אין עדיין תוכנית
-- טיפול" with an invitation to create one, for a plant holding an active version 2.
-- That is worse than a blank: it is a confident statement of the opposite. The
-- existing view-as test asserts only that `GET /v1/plants/{id}` answers 200, which is
-- true whatever these policies say, which is why nothing caught it.
--
-- SELECT only, and only for `is_admin()`. Writing stays owner-only exactly as before:
-- the API already refuses every non-GET carrying the act-as header, and this must not
-- become the thing that makes an administrator's write possible at the database.
-- =============================================================================

create policy care_rules_select_admin
  on public.care_rules for select
  to authenticated
  using (public.is_admin());

comment on policy care_rules_select_admin on public.care_rules is
  'View-as (FINAL section 29): an administrator reads a user''s care rules so the '
  'schedule can be named. SELECT only; every write stays owner-scoped.';

create policy care_plan_versions_select_admin
  on public.care_plan_versions for select
  to authenticated
  using (public.is_admin());

comment on policy care_plan_versions_select_admin on public.care_plan_versions is
  'View-as (FINAL section 29): an administrator reads a user''s plan versions so the '
  'plant dashboard shows the plan that exists. SELECT only.';
