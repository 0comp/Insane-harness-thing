id: T02
title: Model router with manual paste queue
depends: T01
files: router.py, test_router.py

Build `router.py` (import QuotaGovernor from quota.py).
- `class ProviderError(Exception)` and `class AllProvidersBusy(Exception)`.
- A provider is any object with `.name` (str) and `.complete(prompt) -> str` that raises ProviderError on failure.
- `class Router(providers, governor, order)`: `providers` is a dict name->provider, `order` a list of names.
- `complete(prompt) -> (text, provider_name)`: for each name in `order`, skip if `governor.allow(name)` is False; call the provider; on ProviderError try the next; on success call `governor.record(name, tokens=len(text)//4)` and return. If none worked raise AllProvidersBusy.
- `class ManualPasteQueue(path)` with name "manual": `complete(prompt)` appends {"id": n, "prompt": prompt, "answer": null} to a JSON list at `path` and raises ProviderError("queued for human"); `pending() -> list`; `answer(id, text)` stores the answer.
Tests with fake providers: fallback order, quota skip, all-fail raises, queue write and answer.
