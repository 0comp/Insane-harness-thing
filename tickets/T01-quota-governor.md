id: T01
title: Quota governor
depends: none
files: quota.py, test_quota.py

Build `quota.py` with `class QuotaGovernor(path, limits)`.
- `limits` is a dict like {"groq": {"requests_per_day": 100}, "ollama": {"requests_per_day": None}} (None = unlimited).
- Usage persists as JSON at `path`: {"2026-10-28": {"groq": {"requests": 3, "tokens": 1200}}}.
- `allow(provider, today=None) -> bool`: False for unknown providers or when today's requests reached the limit.
- `record(provider, tokens=0, today=None)`: adds one request and the tokens.
- `used(provider, today=None) -> dict` with keys requests and tokens (zeros if none).
- `remaining(provider, today=None) -> int | None` (None when unlimited).
- `today` is an ISO date string; default is today's date. A new day starts at zero.
Tests (unittest, tmp dir): limit reached blocks, unknown provider blocked, persistence across two instances, day rollover.
