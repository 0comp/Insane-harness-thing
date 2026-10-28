#!/usr/bin/env python3
"""Self-building loop for the AI Money Harness.

Run on the human's PC (needs git, Python 3.10+, and Ollama or a free API key):
    python selfbuild.py                # build every ready ticket, one branch (and PR) each
    python selfbuild.py --once         # build one ticket
    python selfbuild.py --dry-run      # show the next ticket and its prompt, change nothing
    python selfbuild.py --no-push      # build locally, do not push
    python selfbuild.py --retry-failed # try failed tickets again

Safety rules (from the vault): a ticket may only write the files it lists, secrets
are scanned for before anything is committed, main is only touched by the one-time
bootstrap commit, and nothing is ever merged. The human merges the pull requests.
Model names and API shapes below are from memory and UNVERIFIED.
"""
import argparse
import datetime
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import setup_harness as setup

VERSION = "0.5 (merge-fix, own-file autocommit)"
ROOT = Path(__file__).resolve().parent
DEFAULT_REMOTE = "https://github.com/0comp/Insane-harness-thing.git"
MAX_ATTEMPTS = 3
PROTECTED = {"setup_harness.py", "test_setup_harness.py", "selfbuild.py", "test_selfbuild.py"}
BOOTSTRAP = ["setup_harness.py", "test_setup_harness.py", "selfbuild.py", "test_selfbuild.py",
             "RULES.md", "README.md", ".gitignore"]
SECRET_PATTERNS = {
    "groq key": r"gsk_[A-Za-z0-9]{20,}",
    "google key": r"AIza[0-9A-Za-z_\-]{30,}",
    "github token": r"(ghp_|github_pat_)[A-Za-z0-9_]{20,}",
    "discord token": r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}",
    "hardcoded secret": r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[\"'][^\"']{16,}[\"']",
}
HEADER_RE = re.compile(r"^[ \t>#*`=_-]*FILE:?[ \t]*[`*]*([A-Za-z0-9_]+\.py)[`*]*[ \t=*_#-]*$",
                       re.MULTILINE | re.IGNORECASE)
FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*\n(.*?)\n```", re.DOTALL)


class TicketError(Exception):
    pass


class ProviderError(Exception):
    pass


class AllProvidersFailed(Exception):
    pass


# ---- tickets and model output ----

def safe_name(name):
    """Flat Python files only; never the bootstrap files."""
    if name in PROTECTED or not re.fullmatch(r"[A-Za-z0-9_]+\.py", name):
        raise TicketError(f"file not allowed: {name}")
    return name


def parse_ticket(path):
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    head, _, body = text.partition("\n\n")
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    if "id" not in meta:
        raise TicketError(f"{path}: missing id")

    def items(v):
        return [x.strip() for x in v.split(",") if x.strip() and x.strip().lower() != "none"]

    t = {"id": meta["id"], "title": meta.get("title", ""), "depends": items(meta.get("depends", "")),
         "files": items(meta.get("files", "")), "body": body.strip()}
    for f in t["files"]:
        safe_name(f)
    if not any(f.startswith("test_") for f in t["files"]):
        raise TicketError(f"{t['id']}: ticket must list a test_*.py file")
    return t


def strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)


def clean_content(content):
    """Drop end markers, markdown fences and blank edges around one file's text."""
    lines = content.strip("\n").split("\n")
    junk = re.compile(r"[ \t=*_#-]*END FILE[ \t=*_#-]*|\s*```\s*|\s*", re.IGNORECASE)
    while lines and junk.fullmatch(lines[-1]):
        lines.pop()
    if lines and re.fullmatch(r"\s*```[A-Za-z0-9_+-]*\s*", lines[0]):
        lines.pop(0)
    while lines and re.fullmatch(r"\s*```\s*|\s*", lines[-1]):
        lines.pop()
    return "\n".join(lines) + "\n"


def parse_files(response):
    """Accepts '=== FILE: x.py ===' blocks (end marker optional, fences tolerated); falls back to
    fenced code blocks whose preceding line names a .py file."""
    text = strip_think(response)
    heads = list(HEADER_RE.finditer(text))
    files = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        files[m.group(1)] = clean_content(text[m.end():end])
    if files:
        return files
    for m in FENCE_RE.finditer(text):
        named = re.findall(r"([A-Za-z0-9_]+\.py)", text[max(0, m.start() - 150):m.start()])
        if named:
            files[named[-1]] = clean_content(m.group(1))
    return files


def scan_secrets(text):
    return [name for name, pat in SECRET_PATTERNS.items() if re.search(pat, text)]


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30]


# ---- model providers: APIs first, the local model only as a last resort ----

DEFAULT_ORDER = ["groq", "gemini", "cloudflare", "ollama"]
NEEDS_KEY = {"groq": ["groq_api_key"], "gemini": ["gemini_api_key"],
             "cloudflare": ["cloudflare_account_id", "cloudflare_api_token"]}
_COOLDOWN = {}      # provider -> monotonic time until which it is skipped
_PROBE_CACHE = {}   # (url, model) -> (ok, reason)

PROBE_PROMPT = (
    "Write exactly two files, in this format and nothing else:\n"
    "=== FILE: probe.py ===\n<content>\n=== END FILE ===\n"
    "=== FILE: test_probe.py ===\n<content>\n=== END FILE ===\n\n"
    "probe.py defines slugify(text): lowercase the text, replace every run of non-alphanumeric "
    "characters with a single '-', and strip leading and trailing '-'. test_probe.py has unittest "
    "tests for it (standard library only)."
)
PROBE_CHECKS = [("Hello, World!", "hello-world"), ("  A  b ", "a-b"), ("---x---", "x"),
                ("", ""), ("a_b9", "a-b9")]


def _post_chat(url, headers, body, timeout, http, pick):
    status, resp = http("POST", url, headers, body, timeout)
    if status != 200:
        raise ProviderError(f"HTTP {status}")
    return pick(resp)


def _groq(cfg, prompt, http):
    return _post_chat("https://api.groq.com/openai/v1/chat/completions",
                      {"Authorization": f"Bearer {cfg['groq_api_key']}"},
                      {"model": cfg.get("groq_model", "llama-3.3-70b-versatile"),
                       "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
                      120, http, lambda r: r["choices"][0]["message"]["content"])


def _gemini(cfg, prompt, http):
    model = cfg.get("gemini_model", "gemini-2.0-flash")
    return _post_chat(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      {"x-goog-api-key": cfg["gemini_api_key"]},
                      {"contents": [{"parts": [{"text": prompt}]}]},
                      120, http, lambda r: r["candidates"][0]["content"]["parts"][0]["text"])


def _cloudflare(cfg, prompt, http):
    model = cfg.get("cloudflare_model", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    return _post_chat(f"https://api.cloudflare.com/client/v4/accounts/{cfg['cloudflare_account_id']}/ai/run/{model}",
                      {"Authorization": f"Bearer {cfg['cloudflare_api_token']}"},
                      {"messages": [{"role": "user", "content": prompt}]},
                      120, http, lambda r: r["result"]["response"])


def _ollama_chat(cfg, prompt, http):
    num_ctx = cfg.get("ollama_num_ctx", 8192)
    if len(prompt) / 3.5 > num_ctx - 1500:  # would be silently truncated by Ollama
        raise ProviderError(f"prompt too long for the local model's {num_ctx}-token context")
    base = cfg.get("ollama_url", "http://localhost:11434")
    return _post_chat(f"{base}/api/chat", None,
                      {"model": cfg.get("ollama_model", "qwen3:14b"),
                       "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False,
                       "options": {"num_ctx": num_ctx, "temperature": 0.2}},
                      600, http, lambda r: r["message"]["content"])


def probe_local(cfg, http):
    """Coding check for the local model: must follow the file format, pass its own tests,
    and pass hidden checks it has not seen. Cached per model for the run."""
    key = (cfg.get("ollama_url"), cfg.get("ollama_model"))
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    try:
        files = parse_files(_ollama_chat(cfg, PROBE_PROMPT, http))
        if set(files) != {"probe.py", "test_probe.py"}:
            raise ProviderError("did not follow the file format")
        with tempfile.TemporaryDirectory() as d:
            for name, content in files.items():
                (Path(d) / name).write_text(content, encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", d, "-p", "test_*.py"],
                               cwd=d, capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise ProviderError("its own tests fail")
            hidden = "from probe import slugify\n" + "".join(
                f"assert slugify({i!r}) == {o!r}, {i!r}\n" for i, o in PROBE_CHECKS)
            r = subprocess.run([sys.executable, "-c", hidden], cwd=d, capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise ProviderError("wrong answers on hidden checks")
        result = (True, "passed the coding probe")
    except Exception as e:  # noqa: BLE001
        result = (False, f"failed the coding probe: {e}")
    _PROBE_CACHE[key] = result
    return result


def _ollama(cfg, prompt, http):
    if cfg.get("local_probe", True):
        ok, why = probe_local(cfg, http)
        if not ok:
            raise ProviderError(f"local model not strong enough ({why})")
    return _ollama_chat(cfg, prompt, http)


PROVIDERS = {"groq": _groq, "gemini": _gemini, "cloudflare": _cloudflare, "ollama": _ollama}


def call_model(cfg, prompt, http, now=time.monotonic):
    """APIs in order; a provider that errors or hits its limit (429) is skipped for a while.
    The local model is only reached when every API is out. Returns (text, provider)."""
    errors = []
    for name in cfg.get("builder_order", DEFAULT_ORDER):
        if name not in PROVIDERS or not all(cfg.get(k) for k in NEEDS_KEY.get(name, [])):
            continue
        if _COOLDOWN.get(name, 0) > now():
            errors.append(f"{name}: cooling down")
            continue
        try:
            return PROVIDERS[name](cfg, prompt, http), name
        except Exception as e:  # noqa: BLE001 - any failure means try the next provider
            _COOLDOWN[name] = now() + (600 if "429" in str(e) else 120)
            errors.append(f"{name}: {e}")
    raise AllProvidersFailed("; ".join(errors) or "no provider configured")


# ---- the builder ----

class Builder:
    def __init__(self, root, cfg, http, push=True, max_attempts=MAX_ATTEMPTS, say=print):
        self.root, self.cfg, self.http = Path(root), cfg, http
        self.push, self.max_attempts, self.say = push, max_attempts, say
        self.state_path = self.root / ".selfbuild" / "state.json"

    # git helpers
    def run_git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def git(self, *args):
        r = self.run_git(*args)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
        return r.stdout.strip()

    # state
    def load_state(self):
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {}

    def save_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2))

    def tickets(self):
        return [parse_ticket(p) for p in sorted((self.root / "tickets").glob("T*.md"))]

    def pick(self, retry_failed=False):
        state = self.load_state()
        done = {i for i, s in state.items() if s["status"] == "done"}
        for t in self.tickets():
            status = state.get(t["id"], {}).get("status")
            if status == "done" or (status == "failed" and not retry_failed):
                continue
            if all(d in done for d in t["depends"]):
                return t
        return None

    def base_branch(self, state):
        """Stack on the last finished ticket so every branch contains all earlier code."""
        for t in reversed(self.tickets()):
            if state.get(t["id"], {}).get("status") == "done":
                return state[t["id"]]["branch"]
        return "main"

    # prompt
    def context(self, t):
        chunks = []
        by_id = {x["id"]: x for x in self.tickets()}
        for d in t["depends"]:
            for f in by_id.get(d, {}).get("files", []):
                p = self.root / f
                if not f.startswith("test_") and p.exists():
                    chunks.append(f"--- {f} ---\n{p.read_text(encoding='utf-8')[:5000]}")
        return "\n".join(chunks)[:12000] or "(none)"

    def prompt(self, t, error=None):
        rules = (self.root / "RULES.md").read_text(encoding="utf-8")[:4000] if (self.root / "RULES.md").exists() else ""
        text = (
            "You are building ONE small ticket of a Python project.\n"
            f"PROJECT RULES:\n{rules}\n"
            "Python 3.10+, standard library only. Tests must not use the network (inject fakes). "
            "Never put keys or tokens in code.\n"
            f"EXISTING CODE YOU MAY IMPORT (do not rewrite it):\n{self.context(t)}\n\n"
            f"TICKET {t['id']}: {t['title']}\n{t['body']}\n\n"
            f"Write exactly these files: {', '.join(t['files'])}\n"
            "Output ONLY this format, one block per file, no markdown fences, no other text:\n"
            "=== FILE: name.py ===\n<full file content>\n=== END FILE ===\n"
        )
        if error:
            text += f"\nYOUR PREVIOUS ATTEMPT FAILED. Fix it. Failure output:\n{error[-3000:]}\n"
        return text

    def validate(self, t, files):
        allowed = set(t["files"])
        if set(files) - allowed:
            raise TicketError(f"files not in ticket: {sorted(set(files) - allowed)}")
        if allowed - set(files):
            wrote = sorted(files) or "no recognisable file blocks"
            raise TicketError(f"missing files: {sorted(allowed - set(files))}; you wrote: {wrote}")
        for name, content in files.items():
            hits = scan_secrets(content)
            if hits:
                raise TicketError(f"secret-looking text in {name}: {hits}")
        return files

    def run_tests(self):
        try:
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(self.root), "-p", "test_*.py"],
                               cwd=self.root, capture_output=True, text=True, timeout=180,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired:
            return False, "tests timed out after 180 s"
        return r.returncode == 0, (r.stdout + r.stderr)[-3000:]

    def report(self, text):
        """Log to the Obsidian Build Plan progress log if the vault folder is configured,
        else to .selfbuild/obsidian_pending.md for later syncing."""
        line = f"- {datetime.date.today().isoformat()} selfbuild: {text}\n"
        vault = (self.cfg.get("obsidian_vault_path") or "").strip()
        note = Path(vault) / "AI Money Harness" / "Build Plan.md" if vault else None
        try:
            if note and note.exists():
                with open(note, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write("\n" + line)
                return
        except OSError:
            pass
        pending = self.root / ".selfbuild" / "obsidian_pending.md"
        pending.parent.mkdir(parents=True, exist_ok=True)
        with open(pending, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)

    # setup of the git repo
    def ensure_repo(self):
        if not (self.root / ".git").exists():
            self.git("init", "-b", "main")
        for key, val in (("user.email", "harness@local"), ("user.name", "AI Money Harness")):
            if self.run_git("config", key).returncode:
                self.git("config", "--local", key, val)
        gi = self.root / ".gitignore"
        if not gi.exists():
            gi.write_text(".selfbuild/\n__pycache__/\n*.pyc\nconfig.json\n.env\n")
        if self.run_git("rev-parse", "HEAD").returncode:
            files = [f for f in BOOTSTRAP + ["tickets"] if (self.root / f).exists()]
            self.git("add", *files)
            self.git("commit", "-m", "Bootstrap: setup script, self-build loop, tickets")
            self.say("Bootstrap commit made on main.")
        self.git("checkout", "main")
        own = [f for f in BOOTSTRAP + ["tickets"] if (self.root / f).exists()]
        self.git("add", *own)
        if self.run_git("diff", "--cached", "--quiet").returncode:  # changed, e.g. a new zip was unpacked
            self.git("commit", "-m", "Update selfbuild files")
            self.say("Committed updated selfbuild files to main.")
        if self.push:
            if self.run_git("remote", "get-url", "origin").returncode:
                self.git("remote", "add", "origin", self.cfg.get("github_repo", DEFAULT_REMOTE))
            r = self.run_git("push", "-u", "origin", "main")
            if r.returncode != 0 and re.search(r"rejected|fetch first|non-fast-forward", r.stderr):
                r = self.sync_with_remote()
            self.say("Pushed main." if r.returncode == 0 else
                     f"Could not push main (continuing locally): {r.stderr.strip()[:300]}")

    def resolve_add_add(self):
        """Both sides added the same file (e.g. .gitignore, README.md): keep both, lose nothing.
        Returns False, leaving the merge untouched, for any other kind of conflict."""
        r = self.run_git("status", "--porcelain")
        unmerged = [ln for ln in r.stdout.splitlines() if ln[:2] in ("AA", "DD", "AU", "UA", "UD", "DU", "UU")]
        if not unmerged or any(ln[:2] != "AA" for ln in unmerged):
            return False
        for ln in unmerged:
            path = ln[3:].strip().strip('"')
            ours = self.run_git("show", f":2:{path}").stdout
            theirs = self.run_git("show", f":3:{path}").stdout
            extra = None
            if path == ".gitignore":  # union of both, no duplicate lines
                out, seen = [], set()
                for line in ours.splitlines() + theirs.splitlines():
                    if line.strip() and line in seen:
                        continue
                    seen.add(line)
                    out.append(line)
                text = "\n".join(out) + "\n"
            elif path.lower().endswith(".md"):  # ours first, the remote's text kept below it
                text = (ours.rstrip("\n") + "\n\n---\n\n# Previous content of this file on GitHub\n\n"
                        + theirs.rstrip("\n") + "\n")
            else:  # keep ours, keep theirs next to it
                text, extra = ours, (path + ".remote", theirs)
            with open(self.root / path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            self.git("add", path)
            if extra:
                with open(self.root / extra[0], "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(extra[1])
                self.git("add", extra[0])
        self.report(f"merge conflicts in {', '.join(ln[3:] for ln in unmerged)} resolved by keeping both versions.")
        return True

    def sync_with_remote(self):
        """The remote already has work: merge it in (never force-push) and push again."""
        self.say("The remote already has commits; merging them into main (no force push).")
        f = self.run_git("fetch", "origin", "main")
        if f.returncode != 0:
            return f
        m = self.run_git("merge", "origin/main", "--allow-unrelated-histories", "--no-edit",
                         "-m", "Merge existing remote work")
        if m.returncode != 0 and self.resolve_add_add():
            m = self.run_git("commit", "--no-edit")
        if m.returncode != 0:
            conflicts = [ln for ln in m.stdout.splitlines() if "CONFLICT" in ln]
            self.run_git("merge", "--abort")
            m.stderr = ("merge conflict, nothing changed. Resolve by hand (git pull --allow-unrelated-histories "
                        "origin main) then rerun. " + " | ".join(conflicts)[:300])
            self.report(f"could not merge the existing remote work into main: {m.stderr[:200]}")
            return m
        self.report("merged the existing remote work into main (no force push).")
        return self.run_git("push", "-u", "origin", "main")

    # one ticket
    def build(self, t):
        state = self.load_state()
        if self.git("status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("uncommitted changes to tracked files; run: git add -A && git commit -m update")
        base = self.base_branch(state)
        branch = f"ticket/{t['id']}-{slug(t['title'])}"
        self.git("checkout", base)
        self.run_git("branch", "-D", branch)
        self.git("checkout", "-b", branch)
        self.say(f"[{t['id']}] {t['title']} (base {base})")
        error, used, ok = None, [], False
        for attempt in range(1, self.max_attempts + 1):
            try:
                text, provider = call_model(self.cfg, self.prompt(t, error), self.http)
                used.append(provider)
                raw = self.root / ".selfbuild" / f"last_response_{t['id']}.txt"
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(f"provider: {provider}\n\n{text}", encoding="utf-8")
                files = self.validate(t, parse_files(text))
            except AllProvidersFailed as e:
                return self._fail(t, state, base, branch, "waiting", f"no model reachable: {e}")
            except TicketError as e:
                self.say(f"  attempt {attempt} via {used[-1]}: rejected ({e})")
                self.say(f"    model said: {text.strip()[:160]!r}  (full text: {raw})")
                error = (f"{e}\nUse EXACTLY this format for every file, with no markdown fences and no commentary:\n"
                         "=== FILE: name.py ===\n<code>\n=== END FILE ===")
                continue
            for name, content in files.items():
                with open(self.root / name, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
            ok, out = self.run_tests()
            self.say(f"  attempt {attempt} via {provider}: {'tests pass' if ok else 'tests fail'}")
            if ok:
                break
            error = out
        if not ok:
            return self._fail(t, state, base, branch, "failed", (error or "")[-300:])
        log = self.root / "BUILD_LOG.md"
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"- {datetime.date.today().isoformat()} {t['id']} {t['title']}: built by "
                     f"{', '.join(sorted(set(used)))}, {len(used)} attempt(s), tests pass. UNREVIEWED.\n")
        self.git("add", *t["files"], "BUILD_LOG.md")
        self.git("commit", "-m", f"{t['id']}: {t['title']}\n\nBuilt by selfbuild ({', '.join(sorted(set(used)))}). "
                                 "Tests pass. Needs human review.")
        pushed = self.push and self.run_git("push", "-u", "origin", branch).returncode == 0
        if pushed and shutil.which("gh"):
            subprocess.run(["gh", "pr", "create", "--base", base, "--head", branch, "--title",
                            f"{t['id']}: {t['title']}", "--body",
                            f"Built automatically by selfbuild. Tests pass. Merge in ticket order.\n\n{t['body'][:800]}"],
                           cwd=self.root, capture_output=True, text=True)
        state[t["id"]] = {"status": "done", "branch": branch, "providers": sorted(set(used))}
        self.save_state(state)
        self.report(f"{t['id']} {t['title']}: built by {', '.join(used)} in {len(used)} attempt(s), tests pass, "
                    f"branch {branch}{' (pushed)' if pushed else ' (not pushed)'}. UNREVIEWED, human merges.")
        self.say(f"  done: branch {branch}" + (" (pushed)" if pushed else " (not pushed)"))
        return True

    def _fail(self, t, state, base, branch, status, reason):
        self.run_git("reset", "--hard")
        self.run_git("clean", "-fdq", "--", *t["files"])
        self.run_git("checkout", base)
        self.run_git("branch", "-D", branch)
        state[t["id"]] = {"status": status, "reason": reason}
        self.save_state(state)
        self.report(f"{t['id']} {t['title']}: {status}. {reason[:200]}")
        self.say(f"  {status}: {reason}")
        return False

    def run(self, once=False, retry_failed=False):
        self.ensure_repo()
        built = 0
        self.report("run started (loop). Order: free APIs first, local model only if no API is left.")
        try:
            while True:
                t = self.pick(retry_failed)
                if not t:
                    self.say("No ready ticket left.")
                    break
                if not self.build(t):
                    break
                built += 1
                if once:
                    break
        finally:
            self.run_git("checkout", "main")
            for (_url, model), (ok, why) in _PROBE_CACHE.items():
                self.report(f"local model {model}: {why}.")
            self.report(f"run finished: {built} ticket(s) built.")
        self.say(f"Built {built} ticket(s). Review and merge the pull requests in ticket order.")
        return built


def main(argv=None, http=setup.real_http):
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(setup.DEFAULT_CONFIG))
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--retry-failed", action="store_true")
    args = p.parse_args(argv)
    print(f"selfbuild {VERSION} - running from {ROOT}")
    cfg = setup.load_config(args.config)
    b = Builder(ROOT, cfg, http, push=not args.no_push)
    if args.dry_run:
        t = b.pick(args.retry_failed)
        print(b.prompt(t) if t else "No ready ticket left.")
        return 0
    try:
        b.run(once=args.once, retry_failed=args.retry_failed)
    except RuntimeError as e:
        print(f"\nStopped: {e}")
        b.report(f"stopped: {str(e)[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
