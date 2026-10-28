id: T04
title: Discord digest with reaction decisions
depends: none
files: digest.py, test_digest.py

Build `digest.py` using only an injected `http(method, url, headers=None, body=None, timeout=None) -> (status, parsed_json)`.
- Base URL https://discord.com/api/v10, header {"Authorization": "Bot <token>", "User-Agent": "ai-money-harness"}.
- `format_item(item) -> str` for item {"id","branch","title","summary"}: text under 1900 chars, truncated with "...".
- `post_digest(http, token, channel_id, items) -> list[str]`: one POST /channels/{id}/messages per item with {"content": text}; then add reactions with PUT /channels/{id}/messages/{mid}/reactions/{emoji}/@me for the check mark and cross mark (emoji URL-encoded with urllib.parse.quote). Return the message ids.
- `poll_decision(http, token, channel_id, message_id, bot_user_id) -> "approve" | "reject" | None`: GET /channels/{id}/messages/{mid}/reactions/{emoji} for each emoji; a user other than the bot counts. Reject wins if both.
- `send_alert(http, token, channel_id, text) -> bool` posts a plain message, True on status 200 or 201.
Tests with a fake http that records calls.
