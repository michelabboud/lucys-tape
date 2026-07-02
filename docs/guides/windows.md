# Lucy's Tape on Windows

## The recommended way: WSL2

Claude Code itself is happiest in WSL2, and if that's where your `~/.claude/projects`
lives, run Lucy's Tape there too — you get the full experience including the systemd
timer. Follow the normal [getting-started guide](getting-started.md) inside your WSL
distro.

## Native Windows (Claude Code on Windows proper)

The Python core is pure stdlib and runs fine on Windows Python 3.9+. The bash `tape`
CLI does not — so you drive the tools directly and schedule with Task Scheduler.

Claude Code's sessions live at `C:\Users\<you>\.claude\projects` — the extractor finds
them via your home directory automatically.

### One-time setup

```powershell
git clone https://github.com/michelabboud/lucys-tape.git $HOME\lucys-tape
cd $HOME\lucys-tape
git remote rename origin upstream
git remote add origin <your-PRIVATE-repo-url>

# first extraction + DB + commit + push
python tools\extract_conversations.py archive
python tools\build_db.py archive
git add -A; git commit -m "chore: refresh archive"; git push -u origin main
```

### The viewer

```powershell
python tools\conversations_viewer.py archive 8124
# → http://127.0.0.1:8124
```

### Daily schedule (Task Scheduler)

Create `refresh.ps1` in the repo root:

```powershell
Set-Location $PSScriptRoot
python tools\extract_conversations.py archive
if ($LASTEXITCODE -ne 0) { exit 1 }
python tools\build_db.py archive
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m ("chore: refresh archive (" + (Get-Date -Format o) + ")")
    git push origin main
}
```

Then register it:

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
           -Argument "-NoProfile -ExecutionPolicy Bypass -File $HOME\lucys-tape\refresh.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 3:30am
Register-ScheduledTask -TaskName "LucysTapeRefresh" -Action $action -Trigger $trigger
```

### Honest caveats vs the bash CLI

The PowerShell path above runs the extractor + redactor + commit + push, but does NOT
include the bash CLI's extra guardrails (independent leak-guard masking pass, sanity
ratchet, disk floor, single-instance lock). The redactor itself — the primary filter —
runs identically everywhere. A first-class `tape.ps1` with full guardrail parity is a
welcome contribution; until then, WSL2 is the belt-and-suspenders path.
