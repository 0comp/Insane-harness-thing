id: T03
title: Append-only ledger
depends: none
files: ledger.py, test_ledger.py

Build `ledger.py` with `class Ledger(path)`: an append-only CSV with header `date,kind,branch,amount,currency,note`.
- `add(kind, branch, amount, note, currency="SEK", date=None)`: kind must be "money" or "quota" (else ValueError). Open the file in append mode only; never rewrite old rows.
- `rows() -> list[dict]` (amount as float).
- `totals() -> dict` mapping kind -> sum of amount.
- `to_markdown_rows(since=None) -> str`: markdown table rows `| date | kind | branch | amount | note |`, optionally only rows on or after the ISO date `since`.
Tests (tmp dir): header written once, rows append, earlier bytes unchanged after another add, bad kind raises, totals.
