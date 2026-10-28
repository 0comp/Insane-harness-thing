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
