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
