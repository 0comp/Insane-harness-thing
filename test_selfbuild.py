import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import selfbuild as sb

GOOD_ADDER = "def add(a, b):\n    return a + b\n"
GOOD_TEST = ("import unittest\nfrom adder import add\n\n\nclass T(unittest.TestCase):\n"
             "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n\n\n"
             "if __name__ == '__main__':\n    unittest.main()\n")
BAD_TEST = GOOD_TEST.replace("3)", "4)")


def block(name, content):
    return f"=== FILE: {name} ===\n{content}=== END FILE ===\n"


def reply(adder=GOOD_ADDER, test=GOOD_TEST):
    return block("adder.py", adder) + block("test_adder.py", test)


class FakeOllama:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.prompts.append(body["messages"][0]["content"])
        return 200, {"message": {"content": self.replies.pop(0)}}


class Unit(unittest.TestCase):
    def test_parse_ticket_and_rules(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "T01-x.md"
            p.write_text("id: T01\ntitle: X\ndepends: none\nfiles: a.py, test_a.py\n\nBody here.\n")
            t = sb.parse_ticket(p)
            self.assertEqual((t["id"], t["depends"], t["files"]), ("T01", [], ["a.py", "test_a.py"]))
            p.write_text("id: T01\nfiles: a.py\n\nno test file")
            with self.assertRaises(sb.TicketError):
                sb.parse_ticket(p)
            p.write_text("id: T01\nfiles: selfbuild.py, test_a.py\n\nx")
            with self.assertRaises(sb.TicketError):
                sb.parse_ticket(p)

    def test_safe_name(self):
        for bad in ["../x.py", "a/b.py", "x.txt", "setup_harness.py", ".hidden.py", "C:\\x.py"]:
            with self.assertRaises(sb.TicketError):
                sb.safe_name(bad)
        self.assertEqual(sb.safe_name("quota.py"), "quota.py")

    def test_parse_files_strips_think_and_fences(self):
        text = "<think>plan</think>\n=== FILE: a.py ===\n```python\nx = 1\n```\n=== END FILE ===\n"
        self.assertEqual(sb.parse_files(text), {"a.py": "x = 1\n"})

    def test_parse_files_tolerates_common_model_formats(self):
        want = {"a.py": "x = 1\n", "test_a.py": "y = 2\n"}
        no_end = "=== FILE: a.py ===\nx = 1\n=== FILE: test_a.py ===\ny = 2\n"
        fenced_all = "```\n=== FILE: a.py ===\nx = 1\n=== END FILE ===\n=== FILE: test_a.py ===\ny = 2\n=== END FILE ===\n```"
        markdown = "### FILE: a.py\n```python\nx = 1\n```\n### FILE: test_a.py\n```python\ny = 2\n```\n"
        bold = "**FILE: `a.py`**\n```python\nx = 1\n```\n\n**FILE: `test_a.py`**\n```python\ny = 2\n```"
        named = "Here is a.py:\n```python\nx = 1\n```\nAnd test_a.py:\n```python\ny = 2\n```"
        for text in (no_end, fenced_all, markdown, bold, named):
            self.assertEqual(sb.parse_files(text), want, text)
        self.assertEqual(sb.parse_files("I cannot help with that."), {})

    def test_scan_secrets(self):
        self.assertTrue(sb.scan_secrets("k = 'gsk_" + "a" * 30 + "'"))
        self.assertTrue(sb.scan_secrets('api_key = "abcdefghijklmnopqrstuvwxyz"'))
        self.assertFalse(sb.scan_secrets("api_key = cfg['groq_api_key']"))

    def setUp(self):
        sb._COOLDOWN.clear()
        sb._PROBE_CACHE.clear()


GOOD_SLUG = ('import re\n\n\ndef slugify(text):\n'
             '    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n')
SLUG_TEST = ('import unittest\nfrom probe import slugify\n\n\nclass T(unittest.TestCase):\n'
             '    def test_a(self):\n        self.assertEqual(slugify("Hello, World!"), "hello-world")\n')


def probe_reply(code=GOOD_SLUG):
    return block("probe.py", code) + block("test_probe.py", SLUG_TEST)


class Router(unittest.TestCase):
    """Order: APIs first, the local model only when no API is left."""

    def setUp(self):
        sb._COOLDOWN.clear()
        sb._PROBE_CACHE.clear()
        self.calls = []
        self.cfg = {"groq_api_key": "k", "gemini_api_key": "k", "cloudflare_account_id": "a",
                    "cloudflare_api_token": "t", "local_probe": False}

    def http(self, status_by_host, local_text="local"):
        def fn(method, url, headers=None, body=None, timeout=None):
            host = next(h for h in ("groq", "googleapis", "cloudflare", "localhost") if h in url)
            self.calls.append(host)
            st = status_by_host.get(host, 200)
            if st != 200:
                return st, {}
            return 200, {"groq": {"choices": [{"message": {"content": "G"}}]},
                         "googleapis": {"candidates": [{"content": {"parts": [{"text": "M"}]}}]},
                         "cloudflare": {"result": {"response": "C"}},
                         "localhost": {"message": {"content": local_text}}}[host]
        return fn

    def test_api_first_local_never_called(self):
        self.assertEqual(sb.call_model(self.cfg, "p", self.http({})), ("G", "groq"))
        self.assertNotIn("localhost", self.calls)

    def test_429_moves_to_next_api(self):
        self.assertEqual(sb.call_model(self.cfg, "p", self.http({"groq": 429}))[1], "gemini")

    def test_local_only_when_every_api_is_out(self):
        out = {"groq": 429, "googleapis": 429, "cloudflare": 500}
        self.assertEqual(sb.call_model(self.cfg, "p", self.http(out)), ("local", "ollama"))
        self.assertEqual(self.calls[-1], "localhost")

    def test_cooldown_skips_an_exhausted_api(self):
        h = self.http({"groq": 429})
        sb.call_model(self.cfg, "p", h)
        self.calls.clear()
        sb.call_model(self.cfg, "p", h)
        self.assertNotIn("groq", self.calls)

    def test_missing_keys_skip_providers(self):
        self.assertEqual(sb.call_model({"local_probe": False}, "p", self.http({}))[1], "ollama")

    def test_prompt_too_long_for_local_context(self):
        cfg = {"local_probe": False, "ollama_num_ctx": 2048}
        with self.assertRaises(sb.AllProvidersFailed):
            sb.call_model(cfg, "x" * 20000, self.http({}))

    def test_strong_local_model_passes_probe(self):
        cfg = {"ollama_url": "http://localhost:1"}
        self.assertTrue(sb.probe_local(cfg, self.http({}, probe_reply()))[0])
        self.assertEqual(sb.call_model(cfg, "p", self.http({}, "built"))[0], "built")

    def test_weak_local_model_is_refused(self):
        wrong = GOOD_SLUG.replace(".strip(", ".rstrip(")  # passes its own test, fails hidden ones
        cfg = {"ollama_url": "http://localhost:1"}
        ok, why = sb.probe_local(cfg, self.http({}, probe_reply(wrong)))
        self.assertFalse(ok)
        self.assertIn("hidden checks", why)
        with self.assertRaises(sb.AllProvidersFailed) as cm:
            sb.call_model(cfg, "p", self.http({}, probe_reply(wrong)))
        self.assertIn("not strong enough", str(cm.exception))

    def test_local_model_ignoring_format_is_refused(self):
        ok, why = sb.probe_local({"ollama_url": "http://localhost:2"}, self.http({}, "I cannot do that"))
        self.assertFalse(ok)
        self.assertIn("file format", why)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RemoteSync(unittest.TestCase):
    """The first push meets a remote that already has commits."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.bare, self.seed, self.root = base / "remote.git", base / "seed", base / "work"
        self.git(base, "init", "--bare", "-b", "main", str(self.bare))
        self.git(base, "init", "-b", "main", str(self.seed))
        self.git(self.seed, "remote", "add", "origin", str(self.bare))
        (self.root / "tickets").mkdir(parents=True)
        (self.root / "tickets" / "T01-x.md").write_text("id: T01\nfiles: a.py, test_a.py\n\nx")
        sb._COOLDOWN.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              cwd=cwd, capture_output=True, text=True)

    def seed_remote(self, name, text):
        (self.seed / name).write_text(text)
        self.git(self.seed, "add", name)
        self.git(self.seed, "commit", "-m", "remote work")
        self.git(self.seed, "push", "origin", "main")

    def builder(self):
        msgs = []
        b = sb.Builder(self.root, {"github_repo": str(self.bare), "local_probe": False}, None,
                       say=msgs.append)
        b.msgs = msgs
        return b

    def test_merges_existing_remote_work_then_pushes(self):
        self.seed_remote("REVIEW.md", "existing work\n")
        b = self.builder()
        b.ensure_repo()
        tree = self.git(self.bare, "ls-tree", "-r", "--name-only", "main").stdout
        self.assertIn("REVIEW.md", tree)        # remote work kept
        self.assertIn("tickets/T01-x.md", tree)  # our bootstrap pushed on top
        self.assertIn("Pushed main.", b.msgs)

    def test_gitignore_and_readme_conflicts_keep_both_versions(self):
        (self.root / "README.md").write_text("ours readme\n")
        self.seed_remote(".gitignore", "something-else\n")
        (self.seed / "README.md").write_text("remote readme\n")
        self.git(self.seed, "add", "README.md")
        self.git(self.seed, "commit", "-m", "readme")
        self.git(self.seed, "push", "origin", "main")
        b = self.builder()
        b.ensure_repo()
        self.assertIn("Pushed main.", b.msgs)
        self.assertFalse((self.root / ".git" / "MERGE_HEAD").exists())
        ignore = self.git(self.bare, "show", "main:.gitignore").stdout
        self.assertIn("something-else", ignore)
        self.assertIn(".selfbuild/", ignore)
        readme = self.git(self.bare, "show", "main:README.md").stdout
        self.assertIn("ours readme", readme)
        self.assertIn("remote readme", readme)
        self.assertEqual(self.git(self.root, "status", "--porcelain", "--untracked-files=no").stdout, "")

    def test_other_conflicts_abort_cleanly(self):
        # a file the remote deleted-vs-modified style conflict is hard to stage; check the guard directly
        b = self.builder()
        b.ensure_repo()
        self.assertFalse(b.resolve_add_add())  # nothing unmerged -> refuses to "resolve"

    def test_updated_selfbuild_files_are_committed_automatically(self):
        b = self.builder()
        b.ensure_repo()
        (self.root / "tickets" / "T01-x.md").write_text("id: T01\nfiles: a.py, test_a.py\n\nupdated\n")
        (self.root / "tickets" / "T02-y.md").write_text("id: T02\nfiles: b.py, test_b.py\n\nnew\n")
        b.ensure_repo()
        self.assertEqual(self.git(self.root, "status", "--porcelain", "--untracked-files=no").stdout, "")
        self.assertIn("T02-y.md", self.git(self.root, "ls-files").stdout)
        self.assertIn("Committed updated selfbuild files to main.", b.msgs)


class Reporting(unittest.TestCase):
    def test_report_appends_to_vault_note_else_pending(self):
        with tempfile.TemporaryDirectory() as d:
            root, vault = Path(d) / "repo", Path(d) / "vault"
            (vault / "AI Money Harness").mkdir(parents=True)
            note = vault / "AI Money Harness" / "Build Plan.md"
            note.write_text("# Build Plan\n- old entry\n")
            b = sb.Builder(root, {"obsidian_vault_path": str(vault)}, None, say=lambda *_: None)
            b.report("hello")
            text = note.read_text()
            self.assertTrue(text.startswith("# Build Plan\n- old entry\n"))
            self.assertIn("selfbuild: hello", text)
            b2 = sb.Builder(root, {"obsidian_vault_path": str(Path(d) / "missing")}, None, say=lambda *_: None)
            b2.report("fallback")
            self.assertIn("fallback", (root / ".selfbuild" / "obsidian_pending.md").read_text())


@unittest.skipUnless(shutil.which("git"), "git not installed")
class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tickets").mkdir()
        (self.root / "tickets" / "T01-adder.md").write_text(
            "id: T01\ntitle: Adder\ndepends: none\nfiles: adder.py, test_adder.py\n\nBuild add(a, b).\n")
        self.cfg = {"ollama_url": "http://x", "ollama_model": "m", "local_probe": False}
        sb._COOLDOWN.clear()
        sb._PROBE_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def builder(self, replies, **kw):
        self.fake = FakeOllama(replies)
        return sb.Builder(self.root, self.cfg, self.fake, push=False, say=lambda *_: None, **kw)

    def branches(self):
        return subprocess.run(["git", "branch", "--list"], cwd=self.root, capture_output=True, text=True).stdout

    def show(self, ref):
        return subprocess.run(["git", "show", ref], cwd=self.root, capture_output=True, text=True)

    def test_builds_ticket_on_own_branch(self):
        b = self.builder([reply()])
        self.assertEqual(b.run(), 1)
        st = json.loads(b.state_path.read_text())["T01"]
        self.assertEqual(st["status"], "done")
        self.assertIn("ticket/T01-adder", self.branches())
        self.assertEqual(self.show("ticket/T01-adder:adder.py").stdout, GOOD_ADDER)
        self.assertNotEqual(self.show("main:adder.py").returncode, 0)  # main untouched
        self.assertIn("T01 Adder: built by ollama", (self.root / ".selfbuild" / "obsidian_pending.md").read_text())
        self.assertIn("UNREVIEWED", self.show("ticket/T01-adder:BUILD_LOG.md").stdout)

    def test_retry_feeds_failure_back(self):
        b = self.builder([reply(test=BAD_TEST), reply()])
        self.assertEqual(b.run(), 1)
        self.assertEqual(len(self.fake.prompts), 2)
        self.assertIn("YOUR PREVIOUS ATTEMPT FAILED", self.fake.prompts[1])
        self.assertIn("AssertionError", self.fake.prompts[1])

    def test_gives_up_and_cleans_up(self):
        b = self.builder([reply(test=BAD_TEST)] * 3)
        self.assertEqual(b.run(), 0)
        self.assertEqual(json.loads(b.state_path.read_text())["T01"]["status"], "failed")
        self.assertNotIn("ticket/T01", self.branches())
        self.assertFalse((self.root / "adder.py").exists())

    def test_rejects_unlisted_file_and_secret(self):
        extra = reply() + block("evil.py", "x = 1\n")
        secret = reply(adder="KEY = 'gsk_" + "a" * 30 + "'\n" + GOOD_ADDER)
        b = self.builder([extra, secret, reply()])
        self.assertEqual(b.run(), 1)  # third attempt is clean
        self.assertIn("files not in ticket", self.fake.prompts[1])
        self.assertIn("secret-looking", self.fake.prompts[2])
        self.assertEqual(self.show("ticket/T01-adder:adder.py").stdout, GOOD_ADDER)
        self.assertNotEqual(self.show("ticket/T01-adder:evil.py").returncode, 0)

    def test_model_down_is_waiting_not_failed(self):
        b = sb.Builder(self.root, self.cfg, lambda *a, **k: (500, {}), push=False, say=lambda *_: None)
        sb._COOLDOWN.clear()
        self.assertEqual(b.run(), 0)
        self.assertEqual(json.loads(b.state_path.read_text())["T01"]["status"], "waiting")
        self.assertIsNotNone(b.pick())  # will be retried on the next run

    def test_stacks_second_ticket_on_first(self):
        (self.root / "tickets" / "T02-double.md").write_text(
            "id: T02\ntitle: Double\ndepends: T01\nfiles: doubler.py, test_doubler.py\n\nUse adder.add.\n")
        doubler = "from adder import add\n\n\ndef double(x):\n    return add(x, x)\n"
        dtest = ("import unittest\nfrom doubler import double\n\n\nclass T(unittest.TestCase):\n"
                 "    def test_d(self):\n        self.assertEqual(double(2), 4)\n")
        b = self.builder([reply(), block("doubler.py", doubler) + block("test_doubler.py", dtest)])
        self.assertEqual(b.run(), 2)
        self.assertEqual(self.show("ticket/T02-double:adder.py").stdout, GOOD_ADDER)  # stacked
        self.assertIn("def add", self.fake.prompts[1])  # dependency code given as context

    def test_missing_files_message_shows_what_model_wrote(self):
        b = self.builder(["Sorry, here is some prose.", reply()])
        self.assertEqual(b.run(), 1)
        self.assertIn("no recognisable file blocks", self.fake.prompts[1])
        self.assertIn("=== FILE: name.py ===", self.fake.prompts[1])
        raw = (self.root / ".selfbuild" / "last_response_T01.txt").read_text()
        self.assertTrue(raw.startswith("provider: ollama"))

    def test_dirty_tree_aborts(self):
        b = self.builder([reply()])
        b.ensure_repo()
        (self.root / "tickets" / "T01-adder.md").write_text("id: T01\nfiles: adder.py, test_adder.py\n\nchanged\n")
        with self.assertRaises(RuntimeError):
            b.build(b.pick())


if __name__ == "__main__":
    unittest.main()
