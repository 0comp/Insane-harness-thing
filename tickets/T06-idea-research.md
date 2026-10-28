id: T06
title: Idea research
depends: T02
files: idea_research.py, test_idea_research.py

Build `idea_research.py` (fake router in tests: `complete(prompt) -> (text, name)`).
- `propose_ideas(router, n=3, known=()) -> list[dict]`: ask for JSON only: a list of {"title","case","cost_upfront" (number),"needs_human" (bool)}. Include `known` titles in the prompt so they are not repeated. Parse the first [...] in the reply; return [] if unparseable.
- `filter_ideas(ideas) -> list[dict]`: drop ideas with cost_upfront not equal to 0, with missing title or case, or whose title is in `known`-style duplicates (case-insensitive repeats within the list).
Tests: parsing, filtering costs, duplicates, garbage reply.
