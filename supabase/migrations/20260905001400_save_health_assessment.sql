-- =============================================================================
-- 0014 · Saving a health assessment.
--
-- Spec: FINAL_SPECIFICATION §16 (health agent), DATABASE_SCHEMA "health_*"
--
-- The 1-4 image constraint added in 0010 is DEFERRABLE INITIALLY DEFERRED and is
-- therefore checked at COMMIT. PostgREST gives every call its own transaction, so
-- an assessment written by one request and its images by the next can never
-- satisfy it: the first commits with zero images and fails. That was noted while
-- building PR 20 and recorded in DATABASE_SCHEMA; this function is the
-- consequence.
--
-- Everything a check produces therefore lands in one transaction:
--
--   1. the immutable health_assessments row,
--   2. its images (1-4, the constraint's whole point),
--   3. observations, possible issues, recommendations,
--   4. sources, if the agent cited any,
--   5. plants.current_health_status.
--
-- §16: "Every successful Health Check updates the Plant's current health status.
-- Previous assessments remain unchanged." Both hold here — nothing in this
-- function touches an existing assessment, and the immutability trigger would
-- refuse if it tried.
--
-- A28, recorded per §37
-- ---------------------
-- §16's flow diagram places "Optional Care adjustment proposal → User approval"
-- *before* "Immutable Health Assessment saved", which would mean an assessment
-- is only recorded once a user approves a care change — and never recorded at all
-- when they decline one. Its own prose says the opposite: "Every successful
-- Health Check updates the Plant's current health status." The prose is
-- implemented. The assessment is saved here, and any care proposal is raised
-- afterwards from the saved row.
--
-- SECURITY INVOKER: everything written belongs to the calling user, and RLS
-- should apply in full.
-- =============================================================================

create or replace function public.save_health_assessment(
  p_plant_id        uuid,
  p_overall_status  health_status,
  p_trend           health_trend,
  p_image_ids       uuid[],
  p_agent_request_id uuid    default null,
  p_confidence_level confidence_level default null,
  p_requires_attention boolean default false,
  p_user_note       text     default null,
  p_insufficient_reason text default null,
  p_observations    jsonb    default '[]'::jsonb,
  p_issues          jsonb    default '[]'::jsonb,
  p_recommendations jsonb    default '[]'::jsonb,
  p_sources         jsonb    default '[]'::jsonb,
  p_raw_result      jsonb    default null
)
returns public.health_assessments
language plpgsql
security invoker
set search_path = public, pg_temp
as $fn$
declare
  v_user_id    uuid := auth.uid();
  v_assessment public.health_assessments;
  v_item       jsonb;
  v_index      integer := 0;
  v_image_id   uuid;
begin
  if v_user_id is null then
    raise exception 'authentication required' using errcode = 'insufficient_privilege';
  end if;

  if p_image_ids is null or array_length(p_image_ids, 1) is null then
    raise exception 'a health assessment needs at least one image'
      using errcode = 'check_violation';
  end if;
  if array_length(p_image_ids, 1) > 4 then
    raise exception 'a health assessment may reference at most four images'
      using errcode = 'check_violation';
  end if;

  -- Every image must belong to this plant. RLS already limits the caller to
  -- their own rows; this additionally stops one plant's photographs being used
  -- to assess another, which would attach a finding to the wrong plant.
  if exists (
    select 1
      from unnest(p_image_ids) as requested(id)
     where not exists (
       select 1 from public.plant_images pi
        where pi.id = requested.id and pi.plant_id = p_plant_id
     )
  ) then
    raise exception 'every image must belong to the plant being assessed'
      using errcode = 'check_violation';
  end if;

  insert into public.health_assessments (
    user_id, plant_id, agent_request_id, overall_status, confidence_level,
    trend, user_note, requires_attention, insufficient_information_reason, raw_result
  )
  values (
    v_user_id, p_plant_id, p_agent_request_id, p_overall_status, p_confidence_level,
    p_trend, p_user_note, p_requires_attention, p_insufficient_reason, p_raw_result
  )
  returning * into v_assessment;

  foreach v_image_id in array p_image_ids loop
    v_index := v_index + 1;
    insert into public.health_assessment_images
      (health_assessment_id, plant_image_id, display_order)
    values (v_assessment.id, v_image_id, v_index);

    -- FINAL §20: an image a model has seen is retained for audit even if the
    -- user later removes it from the gallery.
    update public.plant_images set ai_used = true where id = v_image_id;
  end loop;

  for v_item in select * from jsonb_array_elements(coalesce(p_observations, '[]'::jsonb)) loop
    insert into public.health_observations
      (health_assessment_id, observation_text, confidence_level)
    values (
      v_assessment.id,
      v_item ->> 'observation_text',
      nullif(v_item ->> 'confidence_level', '')::confidence_level
    );
  end loop;

  for v_item in select * from jsonb_array_elements(coalesce(p_issues, '[]'::jsonb)) loop
    insert into public.health_issues
      (health_assessment_id, issue_name, severity, confidence_level, evidence)
    values (
      v_assessment.id,
      v_item ->> 'issue_name',
      nullif(v_item ->> 'severity', '')::smallint,
      nullif(v_item ->> 'confidence_level', '')::confidence_level,
      v_item ->> 'evidence'
    );
  end loop;

  for v_item in select * from jsonb_array_elements(coalesce(p_recommendations, '[]'::jsonb)) loop
    insert into public.health_recommendations
      (health_assessment_id, recommendation_text, priority, requires_care_plan_adjustment)
    values (
      v_assessment.id,
      v_item ->> 'recommendation_text',
      nullif(v_item ->> 'priority', '')::smallint,
      coalesce((v_item ->> 'requires_care_plan_adjustment')::boolean, false)
    );
  end loop;

  for v_item in select * from jsonb_array_elements(coalesce(p_sources, '[]'::jsonb)) loop
    insert into public.health_assessment_sources
      (health_assessment_id, source_class, title, url, publisher, retrieved_at, citation_text)
    values (
      v_assessment.id,
      (v_item ->> 'source_class')::knowledge_source_class,
      v_item ->> 'title',
      v_item ->> 'url',
      v_item ->> 'publisher',
      now(),
      v_item ->> 'citation_text'
    );
  end loop;

  -- §16: every successful check updates the plant's current status. An UNKNOWN
  -- is not a successful check in that sense - it is a record that we could not
  -- tell - so it deliberately leaves the previous status standing rather than
  -- overwriting a real finding with an absence of one.
  if p_overall_status <> 'UNKNOWN' then
    update public.plants
       set current_health_status = p_overall_status
     where id = p_plant_id;
  end if;

  return v_assessment;
end;
$fn$;

revoke all on function public.save_health_assessment(
  uuid, health_status, health_trend, uuid[], uuid, confidence_level, boolean,
  text, text, jsonb, jsonb, jsonb, jsonb, jsonb
) from public;

grant execute on function public.save_health_assessment(
  uuid, health_status, health_trend, uuid[], uuid, confidence_level, boolean,
  text, text, jsonb, jsonb, jsonb, jsonb, jsonb
) to authenticated, service_role;

comment on function public.save_health_assessment is
  'Writes an assessment and everything it produced in one transaction, which the '
  'deferred 1-4 image constraint requires. Leaves previous assessments untouched '
  'and does not overwrite a real status with an UNKNOWN verdict (FINAL §16).';
