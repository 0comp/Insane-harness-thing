id: T08
title: Fiverr gig drafter with approval queue
depends: T05, T07
files: gig_drafter.py, test_gig_drafter.py

Build `gig_drafter.py` (fake router and fake doubter in tests; doubter has `review_with_rewrites(draft, rewrite_fn, kind)`).
- `draft_gig(router, doubter, proposal) -> dict {"status", "gig", "advice"}`: ask the router for JSON {"title","description","packages":[{"name","price","delivery_days"}],"sample_ideas":[...]}; run the text through `doubter.review_with_rewrites`, with a rewrite function that asks the router to revise using the advice. Status is "needs_human_approval" if approved, "escalated" otherwise. NEVER return an "approved" or "live" status: a human approves.
- `queue_for_approval(path, result)`: append one JSON line to `path`.
Tests: approved goes to needs_human_approval, escalate stays escalated, queue file gets one line per call, status is never "approved".
