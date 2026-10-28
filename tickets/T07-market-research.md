id: T07
title: Market research gig proposal
depends: T02, T06
files: market_research.py, test_market_research.py

Build `market_research.py` (fake router in tests).
- `propose_gig(router, idea) -> dict` with keys gig_title, buyer, why_it_sells, free_sources (non-empty list of strings), price_basic (number), verified (always False; every outside fact is UNVERIFIED until a human checks).
- Prompt asks for JSON only and says: free sources only, no legal, medical or financial claims, no impersonation.
- Raise ValueError if the reply is unparseable or free_sources is empty.
Tests: good reply, empty sources raises, garbage raises, verified is False even if the model says true.
