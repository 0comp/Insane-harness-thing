# Claude skills (44)

One folder per skill. Each skill folder holds a `SKILL.md` (with `name` and `description` in its frontmatter) plus any extra files it uses. The folder name matches the skill name.

## Install
Copy the skill folders you want into your agent's skills folder, then restart the agent.
- Claude Code: `~/.claude/skills/` (Windows: `%USERPROFILE%\.claude\skills\`)
- Per project: `<project>/.claude/skills/`
Then run `/setup-matt-pocock-skills` once in each project folder.

## Groups
- Obsidian: obsidian-markdown, obsidian-cli, obsidian-bases, json-canvas, defuddle, knap
- Needed for the AI Money Harness: setup-matt-pocock-skills, wizard, to-spec, to-tickets, implement, tdd, code-review, research, handoff, grill-me, grilling
- Also useful: codebase-design, domain-modeling, prototype, ask-matt
- Everything else: the remaining Matt Pocock skills

## Notes
- Matt Pocock skills: https://github.com/mattpocock/skills (check its LICENSE).
- The Obsidian skills' source was not checked.
- Some skills ship shell scripts (`wizard/template.sh`, `diagnosing-bugs/scripts`, `git-guardrails-claude-code/scripts`). Read them before running.
- Never put API keys or tokens into a skill.
- `agents/openai.yaml` files are for Codex and are ignored by Claude Code.
- Snapshot from 2026-10-28.
