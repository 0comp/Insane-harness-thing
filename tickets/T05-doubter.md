id: T05
title: Doubter with escalation
depends: T02
files: doubter.py, test_doubter.py

Build `doubter.py` (uses a Router from router.py, but tests pass a fake router with `complete(prompt) -> (text, name)`).
- `class Doubter(router, rules_text)`; attribute `log` (list of dicts).
- `review(draft, kind) -> dict {"verdict": "approve" | "block", "advice": str}`: ask the model, in a prompt that includes rules_text and the draft, to answer with JSON only. Parse the first {...} in the reply; if unparseable return a block with advice "unparseable reviewer answer". Append every decision to `self.log`.
- `review_with_rewrites(draft, rewrite_fn, kind="draft", max_rewrites=2) -> (status, draft, advice)`: review; if blocked call `rewrite_fn(draft, advice)` and review again, at most `max_rewrites` rewrites. Return ("approved", ...) or ("escalate", ...) after the rewrites are used up.
Tests: approve first time, approve after one rewrite, escalate after two rewrites, garbage reply blocks.
