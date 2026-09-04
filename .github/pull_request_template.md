## What

<!-- One or two sentences. Reference the plan phase/PR, e.g. "Phase 2 / PR 4". -->

## Spec compliance

<!-- Cite the sections this implements, e.g. FINAL §13, DATABASE_SCHEMA care_rules. -->

- Spec sections:
- Architectural invariants touched:

## Checklist

- [ ] `DEVELOPMENT_PROGRESS.md` checkboxes updated in **this** PR (FINAL §37)
- [ ] Any deviation from the spec is recorded in the spec, not just here (FINAL §37)
- [ ] New domain rules have unit tests (PROJECT_STRUCTURE §10)
- [ ] RLS policies added/verified for any new user-owned table
- [ ] No secrets, no `os.environ` outside `app/config/settings.py`
- [ ] No chain-of-thought persisted or logged
- [ ] Error states and empty states covered where user-facing
