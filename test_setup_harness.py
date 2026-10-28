import json
import tempfile
import unittest
from pathlib import Path

import setup_harness as s

FULL = {
    **s.PUBLIC_DEFAULTS,
    "discord_bot_token": "t",
    "groq_api_key": "g",
    "gemini_api_key": "m",
    "cloudflare_account_id": "a",
    "cloudflare_api_token": "c",
}


def ok_http(method, url, headers=None, body=None):
    if "/api/tags" in url:
        return 200, {"models": [{"name": "qwen3:14b"}]}
    if method == "POST":
        return 200, {}
    return 200, {}


class Tests(unittest.TestCase):
    def test_all_pass(self):
        res = s.run_checks(FULL, ok_http)
        self.assertTrue(all(ok for _, ok, _ in res), res)

    def test_missing_secrets_fail_without_network(self):
        calls = []
        def spy(*a, **k):
            calls.append(a)
            return 200, {}
        res = s.run_checks(dict(s.PUBLIC_DEFAULTS), spy)
        names_failed = [n for n, ok, _ in res if not ok]
        self.assertIn("Discord", names_failed)
        self.assertIn("Groq", names_failed)

    def test_bad_token_reports_status(self):
        res = dict((n, (ok, m)) for n, ok, m in s.run_checks(FULL, lambda *a, **k: (401, {})))
        self.assertFalse(res["Groq"][0])
        self.assertIn("401", res["Groq"][1])

    def test_ollama_model_missing(self):
        def http(method, url, headers=None, body=None):
            return (200, {"models": []}) if "/api/tags" in url else (200, {})
        ok, msg = s.check_ollama(FULL, http)
        self.assertFalse(ok)
        self.assertIn("ollama pull", msg)

    def test_no_discord_post(self):
        seen = []
        def http(method, url, headers=None, body=None):
            seen.append(method)
            return 200, {}
        s.check_discord(FULL, http, post=False)
        self.assertNotIn("POST", seen)

    def test_fill_missing_asks_only_for_missing(self):
        cfg = dict(FULL)
        del cfg["groq_api_key"]
        asked = []
        def ask(prompt):
            asked.append(prompt)
            return "newkey"
        self.assertTrue(s.fill_missing(cfg, ask))
        self.assertEqual(len(asked), 1)
        self.assertEqual(cfg["groq_api_key"], "newkey")

    def test_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "config.json"
            s.save_config(path, FULL)
            self.assertEqual(json.loads(path.read_text())["groq_api_key"], "g")
            self.assertEqual(s.load_config(path)["groq_api_key"], "g")

    def test_main_check_mode_does_not_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            s.save_config(path, FULL)
            def no_prompt(_):
                raise AssertionError("prompted in --check mode")
            self.assertEqual(s.main(["--check", "--config", str(path)], ok_http, no_prompt), 0)


class VaultTests(unittest.TestCase):
    def test_vault_prompt_asked_once(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {}
            self.assertTrue(s.fill_vault(cfg, lambda _p: f' "{d}" '))
            self.assertEqual(cfg["obsidian_vault_path"], d)
            self.assertFalse(s.fill_vault(cfg, lambda _p: 1 / 0))  # not asked again

    def test_skip_is_remembered_and_bad_path_is_not_saved(self):
        cfg = {}
        self.assertTrue(s.fill_vault(cfg, lambda _p: ""))
        self.assertEqual(cfg["obsidian_vault_path"], "")
        cfg = {}
        self.assertFalse(s.fill_vault(cfg, lambda _p: "/no/such/folder"))
        self.assertNotIn("obsidian_vault_path", cfg)


class CleanTests(unittest.TestCase):
    def test_clean_removes_control_chars_and_quotes(self):
        self.assertEqual(s.clean_secret("\x16"), "")
        self.assertEqual(s.clean_secret('  "abc123"\x16 '), "abc123")

    def test_junk_paste_is_not_saved(self):
        cfg = dict(s.PUBLIC_DEFAULTS)
        self.assertFalse(s.fill_missing(cfg, lambda _p: "\x16"))
        self.assertNotIn("groq_api_key", cfg)

    def test_load_config_drops_saved_junk(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            path.write_text(json.dumps({"groq_api_key": "\x16", "gemini_api_key": " good "}))
            cfg = s.load_config(path)
            self.assertNotIn("groq_api_key", cfg)
            self.assertEqual(cfg["gemini_api_key"], "good")


if __name__ == "__main__":
    unittest.main()
