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
