id: T09
title: Master agent quota report and branch review
depends: T01, T03, T04
files: master.py, test_master.py

Build `master.py` (import QuotaGovernor from quota.py and Ledger from ledger.py).
- `priority_order(branches) -> list[str]`: branches are dicts {"name","priority" (lower first),"paused" (bool)}; skip paused; stable sort by priority.
- `quota_report(governor, providers) -> str`: one line per provider: name, used requests, remaining ("unlimited" if None).
- `branch_summary(rows, branch, days=30) -> str`: from Ledger rows (dicts) for this branch, total money and number of money rows; if total money is 0 say the branch is struggling and the human should review it.
- `digest_items(branches, report) -> list[dict]`: items {"id","branch","title","summary"} for T04's post_digest, one per active branch.
Tests: ordering with pause, report format, summary with and without income.
