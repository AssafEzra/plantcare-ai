# PlantCare AI — Testing Strategy

## 1. Purpose

Testing must verify not only that screens work, but that PlantCare AI preserves its domain rules, security boundaries, Agent contracts, and lifecycle guarantees.

## 2. Test Layers

```text
Unit
  ↓
Integration
  ↓
API
  ↓
Security / RLS
  ↓
End-to-End
```

Each layer has a different responsibility.

## 3. Unit Tests

Unit tests cover deterministic domain logic without external services.

Priority areas:

- plant lifecycle transitions;
- identification confirmation rules;
- knowledge status transitions;
- care rule calculations;
- overdue-task behavior;
- skipped-task behavior;
- health status mapping;
- health trend calculation;
- notification scheduling;
- timezone conversion;
- image validation;
- operational preference changes;
- Care Plan version creation;
- immutable Care Events.

Examples:

```text
ACTIVE → ARCHIVED
ARCHIVED → ACTIVE
PENDING_IDENTIFICATION → IDENTIFIED
IDENTIFIED → KNOWLEDGE_PENDING
KNOWLEDGE_PENDING → ACTIVE
```

Invalid transitions must be rejected.

## 4. Agent Contract Tests

Agents must be tested against their schemas independently of the real provider.

Tests should verify:

- valid structured output is accepted;
- malformed JSON is rejected;
- schema-invalid output is rejected;
- missing mandatory fields are handled;
- confidence values remain within allowed ranges;
- unsupported claims are not silently promoted to authoritative data;
- AI failures do not create approved records.

Invalid structured output may be retried automatically up to the configured limit (MVP: maximum 2 retries).

## 5. Agent-Specific Tests

### Identification

Verify:

- candidate ordering;
- confidence classification;
- low-confidence warning;
- `NEEDS_MORE_INFORMATION`;
- `FAILED`;
- no automatic plant mutation before user confirmation;
- identification history is retained.

### Knowledge

Verify:

- draft creation;
- source references;
- approved vs external/unapproved source classification;
- incomplete/failed research;
- admin-only publication;
- published versions are immutable.

### Care

Verify:

- knowledge version is referenced;
- environment and history are considered;
- proposal requires approval;
- operational edits create a new version;
- professional recommendation is not silently changed.

### Health

Verify:

- 1–4 images;
- insufficient evidence produces `UNKNOWN`;
- no definitive diagnosis language is treated as authoritative diagnosis;
- successful assessment updates current plant health status;
- prior assessments remain unchanged;
- care adjustment is proposal-only.

## 6. Integration Tests

Integration tests use an isolated DEV/test Supabase environment.

Cover:

- Authenticated CRUD;
- repositories;
- Storage upload;
- image metadata;
- identification history;
- Knowledge workflow;
- Care Plan versions;
- Care Tasks and Events;
- Health Assessments;
- notification delivery logs.

## 7. RLS / Security Tests

Security testing is mandatory.

For each user-owned table, test:

```text
User A can read User A data
User A cannot read User B data
User A can modify only User A data
User A cannot access admin-only records
```

Also verify:

- anonymous users cannot access protected data;
- service-role usage remains server-side;
- client-supplied `user_id` cannot override authenticated identity;
- client-supplied role cannot grant admin access;
- Storage access follows ownership rules.

## 8. API Tests

Verify:

- authentication;
- authorization;
- validation;
- success envelopes;
- error envelopes;
- HTTP status codes;
- idempotency for AI-triggering POSTs;
- 202 responses for async-style AI operations;
- request IDs;
- safe error messages.

## 9. End-to-End Critical Journeys

At minimum:

### New Plant

```text
Add Plant
→ upload images
→ identify
→ confirm
→ existing Knowledge → ACTIVE
```

And:

```text
Add Plant
→ identify
→ confirm
→ new Species
→ Knowledge Draft
→ KNOWLEDGE_PENDING
→ admin approval
→ ACTIVE
```

### Care

```text
View task
→ Done
→ Care Event
→ next due calculated
```

### Health

```text
Health Check
→ upload 1–4 images
→ analysis
→ result
→ immutable Health Assessment
→ current health status updated
```

### Reporting

```text
User reports Knowledge error
→ admin sees report
→ draft/research workflow
→ published new version
```

## 10. Regression

Every production bug should produce a regression test where practical.

The test suite must run before merging to `main`.

## 11. Test Data

Use deterministic test fixtures.

Never use real user data for automated tests.

Seed test Species and Knowledge versions for stable scenarios.

## 12. AI Testing Policy

Tests should not depend exclusively on live LLM responses.

Use:

- mocked AI provider;
- fixed structured outputs;
- malformed-output fixtures;
- timeout/error fixtures;
- optional controlled provider integration tests.

Live AI tests may be run separately because they are slower, less deterministic, and potentially costly.

## 13. Acceptance Gate

A feature is considered complete only when:

- domain tests pass;
- API tests pass;
- relevant RLS tests pass;
- critical UI flow works;
- error states are covered;
- no authoritative record is created from a failed AI operation.

## Integration tests write to a shared, persistent DEV database

**Added in PR 15, per FINAL_SPECIFICATION §37.** Two properties of the DEV project make a class
of test bug possible that a throwaway database would not:

- **Rows committed through the service role outlive the run.** Tests that use the direct
  `psycopg` connection are rolled back; tests that go through PostgREST are not. Anything the
  second kind creates is still there for the next run, and for every other test file.
- **Some rows can never be removed.** A published `knowledge_version` is undeletable by design
  (FINAL §29), and `knowledge_sources` references it `ON DELETE RESTRICT`, so the `species` row
  underneath it is undeletable too. Test data can therefore be permanent.

Together those mean a generator that produces colliding names does not merely fail its own test —
it poisons every later one. `unique_species_name()` in `tests/integration/conftest.py` is the
required generator for species: letters only, because `normalize_scientific_name()` strips digits
and a hex epithet collapses to one or two letters, giving the whole generator a name space of
about a dozen values. Seventeen such rows accumulated in PR 14 and broke seventeen previously
green tests in an unrelated file.

The rule: **any integration test that commits must generate names that cannot collide**, and must
assume the rows it leaves behind are permanent.

## The journey suite, the RLS matrix, and what they are for

**Added in PR 23, per FINAL_SPECIFICATION §37.**

`tests/e2e/` holds the nine journeys of `PROGRESS §20` plus the knowledge-error
journey from §9 above. Each drives the HTTP API against DEV, start to finish, with
a scripted provider per agent. `tests/security/test_rls_matrix.py` walks every
user-owned table against five axes at the database itself.

The two are deliberately different instruments and neither replaces the other. The
matrix proves the policies; the journeys prove the application does not route around
them. Both failure modes have happened in this codebase — a table shipped without an
INSERT policy, and a repository that relied on a policy which grants administrators
read-all and so listed other users' plants.

**What a journey is for.** Not endpoint coverage — the integration suite already has
that. A journey exists to walk a seam between phases, because that is where every
serious defect in this build has been. The first run of these nine found two more, in
code that had been green for weeks:

- `GET /v1/agent-requests/{id}` did not return `output_summary`, so a client
  polling until COMPLETE could not reach the identification it had just paid for.
  Every unit test passed because none of them was the client.
- `GET /v1/species/{id}/knowledge` returned 500 whenever `source_summary` was NULL,
  which is every version not created by the publication RPC — the seed included.

**Three rules for a journey.**

1. *Walk the client's path.* Read the identification the way the UI reads it, not
   through a service-role query that no browser can make. The first defect above was
   invisible until the test stopped taking a shortcut.
2. *Script the model, never the database.* `TESTING §9`: no test depends on a live
   LLM. An unscripted `MockProvider` raises rather than returning something
   plausible, so a missing dependency override fails loudly instead of making a real
   billable call.
3. *Build fixtures the product could have built.* A knowledge version with five of
   thirteen sections and a null `published_at` is a row publication cannot produce;
   asserting against it tests nothing and hides what it does find behind a 500.

**Two harness concessions, both deliberate.** Journeys drive the scheduler scoped to
one user rather than `POST /v1/internal/tick`, which is global by design and takes
about twenty-five seconds against a DEV database holding a thousand plants; and they
raise A14's rate limit, because a journey compresses days of user actions into
seconds. The tick route's authentication and idempotency, and the limiter's counting,
each have their own tests.

### Two shared quotas the suite runs into

**Added in PR 23.**

**Supabase Auth rate limiting.** Every integration and journey test creates real
accounts through the Auth admin API, which the project rate-limits. One full run is
comfortably inside the budget; iterating on the journeys locally is not, and the
failure surfaces as `AuthApiError: Request rate limit reached` in whichever test was
running when the ceiling was hit — usually not the one that spent the quota. The
journey harness backs off through a burst, which is all backoff can do; a sustained
limit is a wait, not a bug. CI runs the suite once per merge to `dev`.

**The tick is global and the DEV database keeps growing.** `POST /v1/internal/tick`
materialises and sweeps across every user, at roughly four round trips per active
rule. Against DEV — nine hundred plants and a hundred rules as of PR 23 — one call
takes about twenty-five seconds, and the scheduler tests call it repeatedly. That
cost is a property of the endpoint, not of the tests: PR 24 schedules it every
fifteen minutes, so it is worth watching as real plants accumulate. Journeys drive
the scheduler scoped to one user for this reason.

### Test accounts cannot be deleted

**Added in PR 26.** Teardown had called `auth.admin.delete_user` inside
`contextlib.suppress(Exception)` since the first integration test. Every call
failed, and nothing said so: `profiles` cascades from `auth.users`, but
`system_events` refuses DELETE because `FINAL §1.5` makes it append-only, so the
cascade is rejected for any account that ever created a plant. The DEV project
had accumulated 1,375 orphaned accounts, 205 of them administrators, and the Auth
rate limit they helped exhaust was being blamed on whichever suite hit it last.

Three consequences, all now built in:

- `delete_accounts()` in `tests/integration/conftest.py` is the only teardown path.
  It attempts the delete, and **stops attempting after the first structural
  failure** - every later account fails identically, and each attempt spends Auth
  quota the next test needs. A rate-limit error does not stop it, because that one
  is transient.
- What could not be removed is **reported in the terminal summary**, with the
  command that removes it. A silent failure that accumulates is worse than a loud
  one that does not.
- `scripts/purge_dev_test_accounts.py` is the only thing that can actually delete
  them. It disables the immutability triggers for the duration of one transaction,
  which needs table ownership, and it refuses to run against any project but DEV.
  Foreign-key cascades stay enabled throughout - `session_replication_role =
  replica` would have been shorter and would have left orphans.

The rule: **assume every account and every plant a test creates is permanent.**
Generate names that cannot collide, scope assertions to your own rows, and run the
purge script when the project gets crowded.
