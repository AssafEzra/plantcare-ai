-- =============================================================================
-- Seed data for DEV.
--
-- TESTING_STRATEGY §11: use deterministic fixtures, never real user data, and
-- seed test Species and Knowledge versions for stable scenarios.
--
-- Two species are published so the FINAL §34 journey "existing species reuses
-- published Knowledge" has something to reuse. A third species is deliberately
-- left with no knowledge at all, so the opposite journey — confirm, then
-- KNOWLEDGE_PENDING, then admin approval — is exercisable too.
--
-- Idempotent: safe to re-run against an already-seeded database.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Approved sources (FINAL §10: approved domains are preferred)
-- -----------------------------------------------------------------------------
insert into public.approved_sources (name, domain, source_type, reliability_level, notes)
values
  ('Royal Horticultural Society', 'rhs.org.uk', 'HORTICULTURAL_SOCIETY', 5,
   'UK horticultural authority; strong cultivation guidance.'),
  ('Missouri Botanical Garden', 'missouribotanicalgarden.org', 'BOTANICAL_GARDEN', 5,
   'Plant Finder database; reliable species-level care data.'),
  ('Royal Botanic Gardens, Kew — Plants of the World Online', 'powo.science.kew.org',
   'TAXONOMIC_DATABASE', 5,
   'Authoritative for accepted names and synonymy; taxonomy rather than care.'),
  ('North Carolina Extension Gardener Plant Toolbox', 'plants.ces.ncsu.edu',
   'UNIVERSITY_EXTENSION', 4,
   'University extension service; includes toxicity information.'),
  ('University of Florida IFAS Extension', 'edis.ifas.ufl.edu', 'UNIVERSITY_EXTENSION', 4,
   'Peer-reviewed extension publications.'),
  ('ASPCA Toxic and Non-Toxic Plants', 'aspca.org', 'VETERINARY', 5,
   'Authoritative for pet toxicity, which FINAL §10 requires under Toxicity/Safety.')
on conflict (domain) do nothing;

-- -----------------------------------------------------------------------------
-- Species
-- -----------------------------------------------------------------------------
insert into public.species (scientific_name, common_name, family, genus)
values
  ('Monstera deliciosa', 'מונסטרה', 'Araceae', 'monstera'),
  ('Ficus lyrata', 'פיקוס כינורי', 'Moraceae', 'ficus'),
  -- Intentionally left without knowledge, to exercise the draft workflow.
  ('Sansevieria trifasciata', 'סנסיווריה', 'Asparagaceae', 'sansevieria')
on conflict (normalized_name) do nothing;

-- -----------------------------------------------------------------------------
-- Published knowledge, in Hebrew (MVP decision 4).
--
-- Content is illustrative test data, not researched horticultural advice: it has
-- not been through the Knowledge Agent or admin review. Real published knowledge
-- only ever arrives through that workflow.
-- -----------------------------------------------------------------------------
insert into public.knowledge_versions
  (species_id, language, version_number, content, source_summary, is_current, published_at)
select
  s.id, 'he', 1,
  jsonb_build_object(
    'identification', 'עלים גדולים ומחורצים, מטפס טבעי.',
    'description',    'צמח בית פופולרי ממשפחת הלופיים, מקורו ביערות הגשם של מרכז אמריקה.',
    'light',          'אור בהיר ועקיף. שמש ישירה עלולה לגרום לכוויות בעלים.',
    'watering',       'להשקות כאשר 2-3 הסנטימטרים העליונים של המצע יבשים, בערך כל 7 ימים.',
    'soil',           'מצע מנקז היטב על בסיס כבול עם פרליט.',
    'temperature',    '18-27°C. להימנע מטמפרטורות מתחת ל-13°C.',
    'humidity',       'לחות בינונית עד גבוהה, 60% ומעלה.',
    'fertilization',  'דשן מאוזן אחת לחודש באביב ובקיץ.',
    'repotting',      'להחליף עציץ אחת לשנה-שנתיים באביב.',
    'pruning',        'להסיר עלים צהובים או פגומים בבסיס.',
    'propagation',    'ייחורי גזע עם שורש אוויר, במים או במצע.',
    'common_problems','עלים צהובים מרמזים לרוב על השקיית יתר; קצוות חומים על לחות נמוכה.',
    'toxicity',       'רעיל לחתולים ולכלבים בבליעה (גבישי סידן אוקסלט).',
    'sources',        'ראו knowledge_sources לפרטי המקורות.'
  ),
  jsonb_build_object('seeded', true, 'note', 'DEV fixture, not researched content'),
  true, now()
from public.species s
where s.normalized_name = 'monstera deliciosa'
  and not exists (
    select 1 from public.knowledge_versions v
    where v.species_id = s.id and v.language = 'he'
  );

insert into public.knowledge_versions
  (species_id, language, version_number, content, source_summary, is_current, published_at)
select
  s.id, 'he', 1,
  jsonb_build_object(
    'identification', 'עלים גדולים בצורת כינור, ירוק כהה עם עורקים בולטים.',
    'description',    'עץ נוי פנים ממערב אפריקה, רגיש לשינויי מיקום.',
    'light',          'אור בהיר ועקיף, קרוב לחלון מזרחי או מוגן.',
    'watering',       'להשקות כאשר החלק העליון של המצע יבש, בערך כל 7-10 ימים.',
    'soil',           'מצע מנקז היטב, עשיר בחומר אורגני.',
    'temperature',    '18-24°C, ללא רוחות פרצים.',
    'humidity',       'לחות בינונית, 40-60%.',
    'fertilization',  'דשן מאוזן אחת לחודש בעונת הגדילה.',
    'repotting',      'אחת לשנתיים, או כאשר השורשים ממלאים את העציץ.',
    'pruning',        'לגזום ענפים פנימיים לשיפור זרימת אוויר.',
    'propagation',    'ייחורי גזע או הברכת אוויר.',
    'common_problems','כתמים חומים עלולים להעיד על השקיית יתר או על מחסור בלחות.',
    'toxicity',       'רעיל לחיות מחמד בבליעה.',
    'sources',        'ראו knowledge_sources לפרטי המקורות.'
  ),
  jsonb_build_object('seeded', true, 'note', 'DEV fixture, not researched content'),
  true, now()
from public.species s
where s.normalized_name = 'ficus lyrata'
  and not exists (
    select 1 from public.knowledge_versions v
    where v.species_id = s.id and v.language = 'he'
  );

-- -----------------------------------------------------------------------------
-- Provenance for the seeded versions.
--
-- Marked AI_GENERATED_REQUIRES_VERIFICATION on purpose: this content has not gone
-- through the deterministic source-verification step, and labelling it APPROVED
-- would misrepresent it — exactly what FINAL §10 forbids.
-- -----------------------------------------------------------------------------
insert into public.knowledge_sources
  (knowledge_version_id, source_class, title, citation_text, notes)
select
  v.id,
  'AI_GENERATED_REQUIRES_VERIFICATION',
  'DEV seed fixture',
  'תוכן בדיקה בסביבת פיתוח; לא עבר אימות מקורות.',
  'Seeded test data. Never promote to PROD.'
from public.knowledge_versions v
where (v.source_summary ->> 'seeded')::boolean is true
  and not exists (
    select 1 from public.knowledge_sources ks where ks.knowledge_version_id = v.id
  );
