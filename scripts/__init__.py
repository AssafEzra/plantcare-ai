"""Operational scripts.

A package only so the test suite can import from `purge_dev_test_accounts` rather
than keeping a second copy of the trigger list. The comment there is explicit that
two lists would drift, and a teardown that knew about one trigger fewer than the
purge script would fail on exactly the trigger the other list knew about.

Nothing here is imported by `app/`. Each script is still run as a file.
"""
