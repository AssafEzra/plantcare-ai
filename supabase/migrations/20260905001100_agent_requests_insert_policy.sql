-- =============================================================================
-- 0011 · Corrective: let a user start their own agent request.
--
-- Forward fix for 20260905000900 (DEPLOYMENT §11 prefers a corrective migration
-- over editing an applied one).
--
-- `agent_requests` was given a SELECT policy for the owner and an ALL policy for
-- administrators, but no INSERT policy for anyone else. DATABASE_SCHEMA's rule is
-- "AI monitoring is Admin-only except minimal request status for the request
-- owner", which covers reading and says nothing about who creates the row - and
-- the row is created by the user, when they press the button.
--
-- The effect was that every AI-triggering endpoint failed at the first write. It
-- surfaced the moment identification was wired end to end, because nothing before
-- that had ever created one of these rows through a user's client.
-- =============================================================================

create policy agent_requests_insert_own
  on public.agent_requests for insert
  to authenticated
  with check (
    user_id = auth.uid()
    -- A request may only concern the caller's own plant, or no plant at all.
    and (
      plant_id is null
      or exists (
        select 1 from public.plants p
        where p.id = agent_requests.plant_id and p.user_id = auth.uid()
      )
    )
    -- A user starts work; they do not get to declare it finished. Every status
    -- after QUEUED is written by the background task through the service role,
    -- so a client cannot fabricate a SUCCEEDED request with an invented result.
    and status = 'QUEUED'
  );

comment on policy agent_requests_insert_own on public.agent_requests is
  'Users start their own AI requests. They cannot update one afterwards: there is '
  'deliberately no UPDATE policy, so status and stage remain the system''s to set.';
