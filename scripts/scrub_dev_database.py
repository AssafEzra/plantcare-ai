"""Remove test residue from the development database. DEV only.

Why this exists beside `purge_dev_test_accounts.py`
---------------------------------------------------
That script deletes accounts. Most of what the suites leave behind is not owned by
an account and so survives every purge: the knowledge catalogue hangs off `species`,
which belongs to nobody, and storage objects are files rather than rows. By PR 33
that had accumulated to 851 species named `Testus vfmxhivfsmgffv`, 365 knowledge
versions published about them, 2,130 image files belonging to accounts deleted
weeks earlier, and an audit log where 234 of 237 entries pointed at rows that no
longer existed. None of it was reachable by a user; all of it was visible to an
administrator.

Three buckets, not two
----------------------
Rows are classified as **known test** (deleted), **known real** (kept), or
**unclassified** (reported, never deleted).

The third bucket is the point. An allowlist of real accounts is wrong the moment
the product has users - the next person to register is not on it. A pure deny-list
is wrong in the other direction: it is silent when a suite adopts a naming
convention nobody added here, which is how twenty-six PRs of residue went unnoticed.
Naming what it could not classify turns silent accumulation into a line of output,
without ever deleting something it does not recognise.

Three of the five stages need no classification at all - knowledge on a deleted
species, audit rows whose target is gone, and unreferenced storage objects are each
decided by reference rather than by name, and are always safe.

What this cannot do forever
---------------------------
`Testus %` works because a fixture chooses that prefix. A test that identifies a
real photograph creates a real species name, and no pattern will separate it from a
user's. The durable fix is for the factories to mark what they create; the durable
fix for accounts is PR 24, after which real users live in a separate project and
DEV can simply be emptied.

Two deviations from the specification, per FINAL §37
----------------------------------------------------
§29 says a published knowledge version cannot be deleted at all, and §1.5 makes
`admin_audit_log` append-only. Both hold for the product; neither was written to
preserve `Testus ddcbbdibeg` on a development database. Disabling those triggers is
a deliberate administrative act, which is why this is a script that names its
project and refuses to run anywhere else - see §21, which already records physical
deletion as exactly that.

Usage
-----
    uv run python scripts/scrub_dev_database.py           # report only
    uv run python scripts/scrub_dev_database.py --delete  # actually delete

Take a backup first. This cannot be undone.
"""

from __future__ import annotations

import argparse

import psycopg

from scripts.purge_dev_test_accounts import (
    CATALOGUE_TRIGGERS,
    CONSTRAINT_TRIGGERS,
    IMMUTABLE_TRIGGERS,
    PRE_DELETE,
    _where,
    dsn,
)

# The fixtures' species prefix. Deliberately narrow: a species is the one thing here
# that a real flow also creates, so anything wider risks deleting research.
TEST_SPECIES = "scientific_name like 'Testus %'"

# `admin_audit_log.target_id` is a bare uuid with no foreign key, so a row can
# outlive what it describes. A `target_table` missing from this tuple is kept - an
# entry this script does not understand is not evidence that it is stale.
AUDIT_TARGETS = (
    "knowledge_versions",
    "knowledge_drafts",
    "knowledge_reports",
    "approved_sources",
    "profiles",
)

DOOMED_USERS = f"select id from auth.users where {_where()}"
DOOMED_SPECIES = f"select id from public.species where {TEST_SPECIES}"
DOOMED_VERSIONS = f"select id from public.knowledge_versions where species_id in ({DOOMED_SPECIES})"

# No bound parameters anywhere in this module. Every predicate is a literal defined
# above, nothing comes from input, and psycopg would otherwise read the `%` in
# `like '%@example.com'` as a placeholder.
COUNTS = {
    "accounts": f"select count(*) from ({DOOMED_USERS}) x",
    "plants": f"select count(*) from public.plants where user_id in ({DOOMED_USERS})",
    "species": f"select count(*) from ({DOOMED_SPECIES}) x",
    "knowledge_versions": f"select count(*) from ({DOOMED_VERSIONS}) x",
    "knowledge_drafts": (
        f"select count(*) from public.knowledge_drafts where species_id in ({DOOMED_SPECIES})"
    ),
    "knowledge_sources": (
        "select count(*) from public.knowledge_sources"
        f" where knowledge_version_id in ({DOOMED_VERSIONS})"
    ),
}

# Nothing a surviving user owns may point into the catalogue being deleted. Checked
# rather than assumed, and checked *after* the accounts are gone so it describes the
# state the delete will actually meet.
LIVE_REFERENCES = {
    "plants": f"select count(*) from public.plants where species_id in ({DOOMED_SPECIES})",
    "identifications": (
        "select count(*) from public.identifications"
        f" where primary_species_id in ({DOOMED_SPECIES})"
    ),
    "identification_candidates": (
        "select count(*) from public.identification_candidates"
        f" where species_id in ({DOOMED_SPECIES})"
    ),
    "care_plan_versions -> knowledge_version": (
        "select count(*) from public.care_plan_versions"
        f" where knowledge_version_id in ({DOOMED_VERSIONS})"
    ),
    "care_plan_versions -> knowledge_draft": (
        "select count(*) from public.care_plan_versions where knowledge_draft_id in "
        f"(select id from public.knowledge_drafts where species_id in ({DOOMED_SPECIES}))"
    ),
}

# An account that matches no delete rule but looks machine-made: never signed in, no
# display name, owns nothing. A person's account fails all three.
UNCLASSIFIED_ACCOUNTS = f"""
select u.email, u.created_at::date
  from auth.users u
  left join public.profiles p on p.id = u.id
 where u.id not in ({DOOMED_USERS})
   and u.last_sign_in_at is null
   and p.display_name is null
   and not exists (select 1 from public.plants t where t.user_id = u.id)
 order by u.created_at
"""

# A species nothing refers to is either fixture residue under a name this script does
# not know, or a research run that failed before it produced anything.
UNCLASSIFIED_SPECIES = f"""
select s.scientific_name, s.created_at::date
  from public.species s
 where not ({TEST_SPECIES})
   and not exists (select 1 from public.plants t where t.species_id = s.id)
   and not exists (select 1 from public.knowledge_versions k where k.species_id = s.id)
   and not exists (select 1 from public.knowledge_drafts d where d.species_id = s.id)
   and not exists (select 1 from public.identifications i where i.primary_species_id = s.id)
 order by s.created_at
"""


def _stale_audit() -> str:
    """Audit rows whose target will not exist once the catalogue is gone.

    Two halves. The first is a target already missing. The second is a target that
    still exists but is about to be deleted - every `knowledge.publish` entry for a
    `Testus` species. Without the second half a dry run reports a third of what the
    delete actually does, which is worse than no dry run at all.
    """
    missing = " or ".join(
        f"(a.target_table = '{table}'"
        f" and not exists (select 1 from public.{table} t where t.id = a.target_id))"
        for table in AUDIT_TARGETS
    )
    doomed = " or ".join(
        f"(a.target_table = '{table}' and exists (select 1 from public.{table} t"
        f" where t.id = a.target_id and t.species_id in ({DOOMED_SPECIES})))"
        for table in ("knowledge_versions", "knowledge_drafts")
    )
    return f"({missing} or {doomed})"


def _count(conn: psycopg.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def _bucket() -> str:
    from app.config.settings import get_settings

    return get_settings().supabase_storage_bucket


def orphan_objects(conn: psycopg.Connection) -> list[str]:
    """Bucket objects no surviving `plant_images` row refers to.

    Keyed on the reference rather than on whether the path's leading user id still
    exists, so an image whose row is deleted while its owner survives is still
    caught. FINAL §20 retention comes free: an AI-used image keeps its row, so its
    files never appear here.
    """
    return [
        row[0]
        for row in conn.execute(
            """
            select o.name from storage.objects o
             where o.bucket_id = %(bucket)s
               and not exists (
                 select 1 from public.plant_images i
                  where i.storage_path_original = o.name
                     or i.storage_path_processed = o.name
                     or i.storage_path_thumbnail = o.name
               )
             order by o.name
            """,
            {"bucket": _bucket()},
        ).fetchall()
    ]


def report(conn: psycopg.Connection) -> None:
    stale = f"select count(*) from public.admin_audit_log a where {_stale_audit()}"
    print("to delete")
    for name, sql in COUNTS.items():
        print(f"  {name:<24} {_count(conn, sql)}")
    print(f"  {'admin_audit_log':<24} {_count(conn, stale)}")
    print(f"  {'storage objects':<24} {len(orphan_objects(conn))}")

    for label, sql in (("accounts", UNCLASSIFIED_ACCOUNTS), ("species", UNCLASSIFIED_SPECIES)):
        rows = conn.execute(sql).fetchall()
        if rows:
            print(f"\nunclassified {label} - not deleted, look at these")
            for row in rows:
                print(f"  {row[0]}  ({row[1]})")


def scrub(conn: psycopg.Connection) -> dict[str, int]:
    """Every table change in one transaction, with the immutability triggers off.

    No `finally` around the deletes. Postgres aborts the whole transaction on the
    first error, so re-enabling a trigger there would itself raise
    `InFailedSqlTransaction` and *replace* the real exception - which is how the
    first real run of the account purge came to report "current transaction is
    aborted" and nothing about the column that actually refused. The rollback
    restores the triggers regardless: `ALTER TABLE ... DISABLE TRIGGER` is
    transactional.
    """
    triggers = IMMUTABLE_TRIGGERS + CONSTRAINT_TRIGGERS + CATALOGUE_TRIGGERS
    done: dict[str, int] = {}

    with conn.transaction():
        for table, trigger in triggers:
            conn.execute(f"alter table public.{table} disable trigger {trigger}")

        conn.execute(PRE_DELETE.format(where=_where()))
        done["accounts"] = conn.execute(f"delete from auth.users where {_where()}").rowcount

        for name, sql in LIVE_REFERENCES.items():
            live = _count(conn, sql)
            if live:
                raise SystemExit(
                    f"refusing to delete the catalogue: {live} live {name} still reference "
                    "a species marked for deletion. Nothing has been changed."
                )

        done["knowledge_sources"] = conn.execute(
            f"delete from public.knowledge_sources where knowledge_version_id in ({DOOMED_VERSIONS})"
        ).rowcount
        done["knowledge_versions"] = conn.execute(
            f"delete from public.knowledge_versions where species_id in ({DOOMED_SPECIES})"
        ).rowcount
        # `knowledge_drafts` and `knowledge_reports` cascade from species.
        done["species"] = conn.execute(f"delete from public.species where {TEST_SPECIES}").rowcount
        done["admin_audit_log"] = conn.execute(
            f"delete from public.admin_audit_log a where {_stale_audit()}"
        ).rowcount

        for table, trigger in triggers:
            conn.execute(f"alter table public.{table} enable trigger {trigger}")
    return done


def scrub_storage(paths: list[str]) -> int:
    """Delete through the Storage API, never with SQL.

    Deleting the `storage.objects` row leaves the object itself in the bucket -
    invisible to every listing and still counted against the quota. Only the API
    removes both.
    """
    from app.infrastructure.supabase.client import service_client

    bucket = service_client().storage.from_(_bucket())
    for start in range(0, len(paths), 200):
        bucket.remove(paths[start : start + 200])
        print(f"  removed {min(start + 200, len(paths))}/{len(paths)}")
    return len(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove test residue from DEV.")
    parser.add_argument("--delete", action="store_true", help="actually delete; default reports")
    args = parser.parse_args()

    conn = psycopg.connect(dsn(), connect_timeout=30, autocommit=True)
    try:
        report(conn)
        if not args.delete:
            print("\nreport only - pass --delete to remove them")
            return

        orphans = orphan_objects(conn)
        print("\ndeleting rows...")
        for name, count in scrub(conn).items():
            print(f"  {name:<24} {count}")

        if orphans:
            print("\ndeleting storage objects...")
            scrub_storage(orphans)

        print("\nremaining:")
        for table in ("profiles", "plants", "species", "knowledge_versions", "admin_audit_log"):
            print(f"  {table:<24} {_count(conn, f'select count(*) from public.{table}')}")
        print(f"  {'storage.objects':<24} {_count(conn, 'select count(*) from storage.objects')}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
