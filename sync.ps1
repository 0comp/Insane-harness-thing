# Auto-sync for Windows: pull, scan for secrets, commit, push.
# Run by hand or on a schedule (see SYNC.md). Safe to run when nothing changed.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$branch = "main"
$patterns = @(
  'AIza[0-9A-Za-z_\-]{30,}',
  'gsk_[0-9A-Za-z]{20,}',
  'sk-[A-Za-z0-9_\-]{20,}',
  'ghp_[0-9A-Za-z]{30,}',
  'github_pat_[0-9A-Za-z_]{20,}',
  '[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27}',
  'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
)

git pull --rebase --autostash origin $branch
if ($LASTEXITCODE -ne 0) { Write-Error "Pull failed (conflict or no network). Fix by hand, then rerun."; exit 1 }

git add -A
$diff = git diff --cached -U0
foreach ($p in $patterns) {
  if ($diff | Select-String -Pattern $p -Quiet) {
    git reset | Out-Null
    Write-Error "Possible secret matched '$p'. Nothing was committed. Move it to the local config file."
    exit 2
  }
}

git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  git commit -m ("auto-sync " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
  git push origin $branch
  if ($LASTEXITCODE -ne 0) { Write-Error "Push failed."; exit 3 }
} else {
  Write-Host "Nothing to commit."
}
