-- =============================================================================
-- 0010 · Corrective: enforce the 1-4 image rule from the assessment side too.
--
-- Forward fix for 20260905000800 (DEPLOYMENT §11 prefers a corrective migration
-- over editing an applied one).
--
-- The original guard is a row-level constraint trigger on
-- health_assessment_images, so it only fires when an image row is inserted,
-- updated or deleted. That leaves the likelier bug uncaught: persisting a
-- health_assessments row and never attaching the images it was based on. The
-- trigger never fires, and an assessment with zero images survives — contradicting
-- FINAL §16, which requires at least one image and at most four.
--
-- Adding the mirror-image trigger on health_assessments closes it. Both are
-- DEFERRABLE INITIALLY DEFERRED so the application can insert the assessment and
-- its images in either order within one transaction; the check runs at commit,
-- when the set is complete.
-- =============================================================================

create or replace function public.health_assessment_requires_images()
returns trigger
language plpgsql
as $fn$
declare
  n integer;
begin
  -- The assessment may have been removed later in the same transaction.
  if not exists (select 1 from public.health_assessments where id = new.id) then
    return null;
  end if;

  select count(*) into n
    from public.health_assessment_images
   where health_assessment_id = new.id;

  if n < 1 or n > 4 then
    raise exception
      'health assessment % must reference between 1 and 4 images, found %', new.id, n
      using errcode = 'check_violation';
  end if;
  return null;
end;
$fn$;

create constraint trigger health_assessments_require_images
  after insert on public.health_assessments
  deferrable initially deferred
  for each row execute function public.health_assessment_requires_images();

comment on function public.health_assessment_requires_images() is
  'Mirrors health_assessment_image_count_guard() from the assessment side. Without '
  'it, an assessment written with no images at all is never checked, because the '
  'image-side trigger only fires when an image row changes (FINAL §16).';
