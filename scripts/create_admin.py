r"""Create an ADMIN account, or promote an existing one.

Nothing in the running application can do this, by design. A new signup gets
`profiles.role` default `'USER'`, `ProfileUpdateRequest` forbids the field, and a
BEFORE UPDATE trigger raises `insufficient_privilege` if the account holder tries
to change it (FINAL 22, 26; TESTING_STRATEGY 7). An administrator can therefore
only be minted from a connection carrying `rolbypassrls` - which the service-role
key does and no browser session ever will.

That is a deliberate dead end in the product, and this script is the documented
way out of it. Without one, the knowledge lives in somebody's memory, and the
moment it is needed - provisioning the first administrator of a fresh project - is
the moment nobody remembers.

Publishing it costs nothing. It is a lock diagram, not a key: it reads
SUPABASE_SERVICE_ROLE_KEY from `.env`, which is git-ignored and has never been
committed, and anyone holding that key could do this in three lines regardless.

    uv run python scripts/create_admin.py

Run it in a terminal - the password is prompted, never an argument, so it stays
out of shell history. Point it at whichever project `.env` currently names, and
check that line before running it against anything but DEV.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from dotenv import dotenv_values

from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env = dotenv_values(ROOT / ".env")
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from .env")
        return 1

    admin = create_client(url, key)
    print(f"Target project: {url}\n")

    email = input("Email: ").strip()
    if not email:
        print("An email is required.")
        return 1

    users = admin.auth.admin.list_users()
    existing = next((u for u in users if u.email == email), None)

    if existing is not None:
        # Promotion rather than creation. Offered because the usual reason this
        # script is run twice is that an account already exists and was never
        # given the role.
        print(f"{email} already exists ({existing.id}).")
        if input("Promote it to ADMIN? [y/N]: ").strip().lower() != "y":
            print("Nothing changed.")
            return 1
        user_id = existing.id
    else:
        password = getpass.getpass("Password: ")
        if len(password) < 8:
            print("Supabase requires at least 8 characters. Nothing changed.")
            return 1
        if password != getpass.getpass("Confirm:  "):
            print("They do not match. Nothing changed.")
            return 1
        display_name = input("Display name [Admin]: ").strip() or "Admin"

        created = admin.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                # Confirmed here rather than by email: this is an operator
                # provisioning an account deliberately, not somebody proving they
                # own a mailbox. An unconfirmed admin cannot sign in at all.
                "email_confirm": True,
                "user_metadata": {"display_name": display_name},
            }
        )
        user_id = created.user.id
        print(f"\nIdentity created: {user_id}")

    # `on_auth_user_created` provisions profiles and notification_preferences on
    # the auth.users insert, so only the role is set here.
    admin.table("profiles").update({"role": "ADMIN"}).eq("id", user_id).execute()

    # Verify rather than announce. A role that silently failed to apply produces
    # an account that signs in and then behaves as an ordinary user, which is a
    # miserable thing to diagnose a week later.
    profile = admin.table("profiles").select("role").eq("id", user_id).execute().data
    prefs = (
        admin.table("notification_preferences")
        .select("user_id")
        .eq("user_id", user_id)
        .execute()
        .data
    )
    # The client types `.data` as a JSON union, so narrow before indexing.
    first = profile[0] if profile else None
    role = str(first.get("role")) if isinstance(first, dict) else "MISSING"
    print(f"  profiles.role           : {role}")
    print(f"  notification_preferences: {'present' if prefs else 'MISSING'}")

    if role != "ADMIN" or not prefs:
        print("\nSomething is wrong above. Do not rely on this account.")
        return 1

    print(f"\nDone. {email} is an administrator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
