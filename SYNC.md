# Syncing with GitHub

Claude (in the chat) cannot push to GitHub. The PC does it. Two scripts do pull, secret scan, commit and push in one go.

## One-time setup
1. Install Git. Clone or initialise the repo (see README), and run `git push -u origin main` once. A browser window asks you to log in to GitHub; Git Credential Manager remembers it.
2. Run the script once by hand: `powershell -ExecutionPolicy Bypass -File sync.ps1` (Windows) or `./sync.sh` (macOS/Linux). Check it pushes.

## Make it automatic (Windows, every 15 minutes)
```
schtasks /create /sc minute /mo 15 /tn "HarnessSync" /tr "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\Insane-harness-thing\sync.ps1"
```
Remove it with `schtasks /delete /tn "HarnessSync" /f`. On macOS/Linux use cron: `*/15 * * * * /path/to/Insane-harness-thing/sync.sh`.

## What it does
- Pulls the latest first (`--rebase --autostash`), so edits from other machines are merged before you push.
- Scans the staged changes for API-key shapes (Gemini, Groq, OpenAI-style, GitHub, Discord tokens, private keys). If one matches, it commits nothing and exits.
- Commits only when something changed, then pushes.
- A merge conflict or failed push stops the script with an error. Fix it by hand, then rerun.

## Syncing the Obsidian vault
Either copy `AI Money Harness/` into `docs/` before syncing, or install the "Obsidian Git" community plugin in the vault and set auto commit, push and pull every few minutes. Keep the vault free of secrets either way.

## Working with Claude in the chat
At the start of a build session, upload the latest repo zip (GitHub: Code > Download ZIP). Claude adds code and hands back a zip; unzip it over the repo and let the sync script push. If the repo stays public, Claude can also read single files from it by link.
