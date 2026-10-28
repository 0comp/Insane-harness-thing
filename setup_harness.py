#!/usr/bin/env python3
"""Step 0 of the AI Money Harness: setup and live key tests.

Standard library only. Run on the human's PC:
    python setup_harness.py            # ask for missing values, test everything
    python setup_harness.py --show-input        # visible input, pasting works
    python setup_harness.py --check    # no prompts, only test what is saved
    python setup_harness.py --no-discord-post   # skip the Discord test message

Secrets are stored only in the local config file (default
~/.ai-money-harness/config.json), never in the repo or the Obsidian vault.
API endpoints below are from memory and UNVERIFIED; fix them if a test fails.
"""
import argparse
import getpass
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".ai-money-harness" / "config.json"

# Public IDs (not secrets), from the Build Plan progress log, 2026-10-28.
PUBLIC_DEFAULTS = {
    "discord_guild_id": "1564816384284958831",
    "discord_channel_digest": "1564816634990960790",
    "discord_channel_alerts": "1564816742805540925",
    "discord_channel_log": "1564816760425685032",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen3:14b",
}

SECRET_KEYS = [
    ("discord_bot_token", "Discord bot token"),
    ("groq_api_key", "Groq API key"),
    ("gemini_api_key", "Gemini API key"),
    ("cloudflare_account_id", "Cloudflare account ID"),
    ("cloudflare_api_token", "Cloudflare API token"),
]


def real_http(method, url, headers=None, body=None, timeout=15):
    """Return (status, parsed_json_or_text). Never raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "ai-money-harness/0.1")  # some APIs block Python's default
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode(errors="replace")
    except Exception as e:  # network down, DNS, timeout
        return 0, str(e)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


# ---- checks: each returns (ok: bool, message: str) ----

def check_discord(cfg, http, post=True):
    token = cfg.get("discord_bot_token")
    if not token:
        return False, "no bot token saved"
    auth = {"Authorization": f"Bot {token}", "User-Agent": "ai-money-harness (setup, 0)"}
    status, _ = http("GET", "https://discord.com/api/v10/users/@me", auth)
    if status != 200:
        return False, f"token rejected (HTTP {status})"
    status, _ = http("GET", f"https://discord.com/api/v10/guilds/{cfg['discord_guild_id']}", auth)
    if status != 200:
        return False, f"bot is not in the server or the guild ID is wrong (HTTP {status})"
    if post:
        status, _ = http(
            "POST",
            f"https://discord.com/api/v10/channels/{cfg['discord_channel_log']}/messages",
            auth,
            {"content": "Harness setup test: the bot can post here."},
        )
        if status not in (200, 201):
            return False, f"cannot post to #log (HTTP {status}); check channel permissions"
        return True, "token ok, bot in server, test message posted to #log"
    return True, "token ok, bot in server (no test message posted)"


def check_groq(cfg, http, **_):
    key = cfg.get("groq_api_key")
    if not key:
        return False, "no key saved"
    status, _ = http("GET", "https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}"})
    return (status == 200, "key ok" if status == 200 else f"key rejected (HTTP {status})")


def check_gemini(cfg, http, **_):
    key = cfg.get("gemini_api_key")
    if not key:
        return False, "no key saved"
    status, _ = http("GET", "https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key})
    return (status == 200, "key ok" if status == 200 else f"key rejected (HTTP {status})")


def check_cloudflare(cfg, http, **_):
    acct, tok = cfg.get("cloudflare_account_id"), cfg.get("cloudflare_api_token")
    if not acct or not tok:
        return False, "account ID or token missing"
    status, _ = http(
        "GET",
        f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/models/search?per_page=1",
        {"Authorization": f"Bearer {tok}"},
    )
    return (status == 200, "token ok, Workers AI reachable" if status == 200 else f"rejected (HTTP {status})")


def check_ollama(cfg, http, **_):
    base = cfg.get("ollama_url", PUBLIC_DEFAULTS["ollama_url"])
    model = cfg.get("ollama_model", PUBLIC_DEFAULTS["ollama_model"])
    status, body = http("GET", f"{base}/api/tags")
    if status != 200:
        return False, "Ollama is not running (start it, then rerun)"
    names = [m.get("name") for m in body.get("models", [])] if isinstance(body, dict) else []
    if model not in names:
        return False, f"Ollama runs but model {model} is not pulled (run: ollama pull {model})"
    return True, f"Ollama runs and {model} is installed (check GPU use with: ollama ps)"


CHECKS = [
    ("Discord", check_discord),
    ("Groq", check_groq),
    ("Gemini", check_gemini),
    ("Cloudflare Workers AI", check_cloudflare),
    ("Ollama (local)", check_ollama),
]


def clean_secret(value):
    """Strip control characters (Windows getpass turns Ctrl+V into one), whitespace and quotes."""
    value = "".join(ch for ch in (value or "") if ch.isprintable())
    return value.strip().strip("\"'").strip()


# ---- config ----

def load_config(path):
    cfg = dict(PUBLIC_DEFAULTS)
    if Path(path).exists():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    for key, _label in SECRET_KEYS:  # repair or drop junk saved by an earlier run
        cleaned = clean_secret(cfg.get(key))
        if cleaned:
            cfg[key] = cleaned
        else:
            cfg.pop(key, None)
    return cfg


def save_config(path, cfg):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # no effect on Windows; harmless
    except OSError:
        pass


def fill_missing(cfg, ask_secret=getpass.getpass):
    """Ask only for secrets that are not saved yet. Returns True if anything was added."""
    changed = False
    for key, label in SECRET_KEYS:
        if not cfg.get(key):
            raw = ask_secret(f"{label} (Enter to skip): ")
            value = clean_secret(raw)
            if raw.strip() and not value:
                print("  Nothing usable was pasted (Ctrl+V does not work in hidden input). "
                      "Rerun with --show-input, or right-click to paste.")
            if value:
                cfg[key] = value
                changed = True
    return changed


def fill_vault(cfg, ask=input):
    """Optional, not secret: the Obsidian vault folder, so the build can log into it."""
    if "obsidian_vault_path" in cfg:
        return False
    raw = ask("Folder of your Obsidian vault, so the build can log to it (Enter to skip): ").strip().strip("\"'")
    if raw and not Path(raw).is_dir():
        print("  That folder does not exist; skipping for now (will ask again next time).")
        return False
    cfg["obsidian_vault_path"] = raw  # empty string = skipped, do not ask again
    return True


def run_checks(cfg, http, post=True):
    results = []
    for name, fn in CHECKS:
        ok, msg = fn(cfg, http, post=post)
        results.append((name, ok, msg))
    return results


def main(argv=None, http=real_http, ask_secret=getpass.getpass):
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--check", action="store_true", help="no prompts, test saved values only")
    p.add_argument("--no-discord-post", action="store_true")
    p.add_argument("--show-input", action="store_true",
                   help="show what you type/paste (use this if pasting into hidden input fails)")
    args = p.parse_args(argv)

    ask = input if args.show_input else ask_secret
    cfg = load_config(args.config)
    changed = False
    if not args.check:
        changed = fill_missing(cfg, ask)
        changed = fill_vault(cfg) or changed
    if changed:
        save_config(args.config, cfg)
        print(f"Saved to {args.config}")

    results = run_checks(cfg, http, post=not args.no_discord_post)
    for name, ok, msg in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {msg}")
    failed = [n for n, ok, _ in results if not ok]
    print("\nStep 0 done." if not failed else f"\nStill failing: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
