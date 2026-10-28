# AI Money Harness (self-building)

The harness builds itself from small tickets in `tickets/`. One command:

    python selfbuild.py

For each ready ticket it asks a free API model (Groq, then Gemini, then Cloudflare). The local Ollama model is used ONLY when every API is out or failing, and only if it first passes a built-in coding probe (it must follow the file format, pass its own tests, and pass hidden checks); a model that fails the probe is never used
to write the code and tests, runs the tests, retries up to 3 times with the error fed back,
then commits to its own branch `ticket/Txx-name`, pushes it, and opens a pull request if the
GitHub CLI (`gh`) is installed. Branches are stacked: each is based on the previous ticket.
**You merge the pull requests in ticket order. Nothing is merged automatically.**

## First time
1. `python setup_harness.py --show-input` (saves keys to `~/.ai-money-harness/config.json`, tests them)
2. `python -m unittest`
3. `python selfbuild.py --dry-run` (shows the next ticket and prompt, changes nothing)
4. `python selfbuild.py`

The first run makes one bootstrap commit on `main` and pushes it to the repo in `DEFAULT_REMOTE`
(`selfbuild.py`). Git needs a login that works: use your GitHub token when asked for a password.

## Options
`--once` build one ticket - `--no-push` stay local - `--retry-failed` try failed tickets again.
State is in `.selfbuild/state.json` (ignored by git). A ticket marked `waiting` means no model
was reachable (start Ollama); it retries on the next run. Add tickets by dropping `Txx-name.md`
files into `tickets/` (see the existing ones for the format).

## Safety
A ticket can only write the files it lists (flat `.py` files, never the bootstrap files). Output
is scanned for key-like strings before commit. Rules the model sees are in `RULES.md`.
Everything the models produce is UNREVIEWED until you merge it.

## Logging to Obsidian
`setup_harness.py` asks once for your vault folder (Enter to skip). When set, every run, ticket result,
failure and the local-model probe result is appended to `AI Money Harness/Build Plan.md` (progress log).
If not set, entries go to `.selfbuild/obsidian_pending.md` instead. To change the folder later, edit
`obsidian_vault_path` in `~/.ai-money-harness/config.json`.

---

# Previous content of this file on GitHub

# Insane harness thing

A hobby project: a harness of AI agents (several models, free tiers only) that tries ideas for earning money online. A human approves anything public or involving money. Budget: $0.

The plan, rules and decisions live in the Obsidian vault (`AI Money Harness/`). Start with `00 Index.md` there. A copy of the notes can be kept in `docs/`.

## Layout
- `skills/` : 44 agent skills (one folder each, `SKILL.md` inside). Copy into `~/.claude/skills/` for Claude Code, or upload one zip per skill in Claude.
- `src/` : the harness code (Python). Build order: setup script, router and quota governor, ledger, Discord digest bot, doubter, idea research, market research, Fiverr gig drafter, master agent.
- `docs/` : optional copy of the vault notes.
- `sync.ps1` / `sync.sh` : pull, secret scan, commit, push. See `SYNC.md`.

## Rules for this repo
- Never commit secrets: API keys, Discord token, payout or identity details. Keys live in a local config file that `.gitignore` excludes.
- Do not automate logins to consumer chat accounts.
- Everything touching money or public posting needs human approval.

## Third-party material
`skills/` mostly comes from https://github.com/mattpocock/skills (check its LICENSE before keeping this repo public). The Obsidian skills' source has not been checked.
