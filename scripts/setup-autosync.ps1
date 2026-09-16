<#
.SYNOPSIS
    One-command setup: make this machine auto-sync fresh-eyes-review from GitHub.

.DESCRIPTION
    Run this once (Windows PowerShell 5.1 is enough, no admin rights needed):

      1) verify the sync script and this machine's git/python are usable,
      2) resolve the DSH home the way DSH does ($DSH_HOME, then ~/.dsh),
      3) run the first full sync now (clone/pull -> copy -> SHA256 verify -> suite),
      4) register a Windows scheduled task that repeats every N minutes,
      5) trigger that task once and confirm it wrote a fresh OK log line, so the
         registration itself is verified instead of merely assumed.

    After this, nothing else is needed: the task pulls from GitHub and mirrors the
    skill into <DSH_HOME>/skills, where DSH hot-discovers it (no restart). Status
    is one line per run in <repo>/scripts/sync-fresh-eyes-review.log.

    NOTE: this file is intentionally ASCII-only, like sync-skill.ps1. Windows
    PowerShell 5.1 decodes a BOM-less script as ANSI, so non-ASCII text would
    become mojibake and break parsing. Keep it ASCII.

.PARAMETER DshHome
    DSH home directory. Defaults to $DSH_HOME, then ~/.dsh.

.PARAMETER IntervalMinutes
    Repeat interval of the scheduled task, in minutes. Default 60, minimum 15.
    This skill changes rarely, so a short tick only adds noise.

.PARAMETER TaskName
    Name of the Windows scheduled task. Default "FreshEyesReview Skill Sync".

.PARAMETER RepoPath
    Working clone location. Default: <DSH_HOME>/tmp/fresh-eyes-review-repo.

.PARAMETER Uninstall
    Delete the scheduled task instead of registering it. The installed skill and
    the clone are left untouched.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup-autosync.ps1
    Register/refresh the auto-sync task with the default 60 minute interval.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup-autosync.ps1 -Uninstall
    Remove the scheduled task.

.NOTES
    Exit code: 0 = auto-sync registered and verified (or removed); 1 = a step failed.
    Writes: <DSH_HOME>/skills/fresh-eyes-review, the working clone, the log, and one
    scheduled task. No admin rights, no service, no DSH restart.
#>
[CmdletBinding()]
param(
    [string] $DshHome,
    [int]    $IntervalMinutes = 60,
    [string] $TaskName = 'FreshEyesReview Skill Sync',
    [string] $RepoPath,
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

$syncPs1 = Join-Path $PSScriptRoot 'sync-skill.ps1'
$logFile = Join-Path $PSScriptRoot 'sync-fresh-eyes-review.log'

function Fail {
    param([Parameter(Mandatory)][string] $Message)
    Write-Output "[FAIL] $Message"
    exit 1
}

function Step {
    param([Parameter(Mandatory)][string] $Message)
    Write-Output "[....] $Message"
}

function Ok {
    param([Parameter(Mandatory)][string] $Message)
    Write-Output "[ OK ] $Message"
}

if ($Uninstall) {
    Step "removing scheduled task: $TaskName"
    & schtasks.exe /delete /tn $TaskName /f 2>&1 | Out-Null
    $code = $LASTEXITCODE
    if ($code -ne 0 -and $code -ne 1) { Fail "schtasks /delete failed (exit $code)" }
    Ok 'scheduled task removed (the installed skill and the clone stay on disk)'
    exit 0
}

# ---- 0) sanity ---------------------------------------------------------------
if (-not (Test-Path $syncPs1)) { Fail "missing $syncPs1" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'git is not on PATH.' }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail 'python is not on PATH (the sync verifies the installed copy with it).' }

# ---- 1) resolve DSH home -----------------------------------------------------
if (-not $DshHome) { $DshHome = $env:DSH_HOME }
if (-not $DshHome -or -not $DshHome.Trim()) {
    $homePath = $env:USERPROFILE
    if (-not $homePath) { $homePath = [Environment]::GetFolderPath('UserProfile') }
    if (-not $homePath) { Fail 'cannot resolve ~/.dsh; pass -DshHome <path>' }
    $DshHome = Join-Path $homePath '.dsh'
}
$DshHome = $DshHome.Trim()
if (-not (Test-Path $DshHome)) { Fail "DSH home does not exist: $DshHome" }
if (-not (Test-Path (Join-Path $DshHome 'skills')) -and
    -not (Test-Path (Join-Path $DshHome 'profiles'))) {
    Fail "$DshHome does not look like a DSH home (no skills/ or profiles/ inside)"
}

if (-not $RepoPath -or -not $RepoPath.Trim()) {
    $RepoPath = Join-Path (Join-Path $DshHome 'tmp') 'fresh-eyes-review-repo'
}
$RepoPath = $RepoPath.Trim()

if ($IntervalMinutes -lt 15) { Fail 'IntervalMinutes must be >= 15 (this skill changes rarely; a shorter tick only adds noise)' }

Write-Output "sync script : $syncPs1"
Write-Output "DSH home    : $DshHome"
Write-Output "clone       : $RepoPath"
Write-Output "task name   : $TaskName"
Write-Output "interval    : every $IntervalMinutes minute(s)"
Write-Output ''

# ---- 2) first sync now (also proves GitHub is reachable with stored credentials)
Step 'first sync (clone/pull + copy + verify + suite)'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $syncPs1 -DshHome $DshHome -RepoPath $RepoPath
if ($LASTEXITCODE -ne 0) {
    Fail "first sync failed (exit $LASTEXITCODE). If this is an authentication error, make sure this machine can reach GitHub and has stored credentials for it (git credential manager)."
}
Ok 'first sync verified'

# ---- 3) register the repeating task -----------------------------------------
# -DshHome is passed explicitly: a scheduled task does NOT inherit $DSH_HOME,
# because the DSH launcher sets that variable only inside its own process tree.
$taskCmd = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass' +
           " -File `"$syncPs1`" -Quiet -DshHome `"$DshHome`" -RepoPath `"$RepoPath`""

# schtasks /tr has a 261 character limit; refuse loudly instead of truncating.
if ($taskCmd.Length -gt 261) {
    Fail "the task command is $($taskCmd.Length) chars, over schtasks' 261 limit. Move the repo to a shorter path (pass -RepoPath)."
}

Step "registering scheduled task: $TaskName"
& schtasks.exe /create /tn $TaskName /tr $taskCmd /sc minute /mo $IntervalMinutes /f 2>&1 | ForEach-Object { $_ }
if ($LASTEXITCODE -ne 0) {
    Fail "schtasks /create failed (exit $LASTEXITCODE). Try running as this user from a normal console; no admin rights are required for a user-level task."
}
Ok "scheduled task registered (every $IntervalMinutes minute(s))"

# ---- 3b) the task must also run on battery -----------------------------------
# schtasks defaults to DisallowStartIfOnBatteries = true, and that failure is
# silent: on a laptop the task never starts, /run still reports SUCCESS, and the
# status just sits at "Queued". Set both battery flags off by re-registering the
# task from its own XML.
Step 'clearing the battery-power restrictions (they would silently skip runs)'
$taskXmlPath = Join-Path $env:TEMP 'fresh-eyes-review-task.xml'
$prevPref = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & schtasks.exe /query /tn $TaskName /xml ONE 2>$null | Set-Content -Path $taskXmlPath -Encoding Unicode
    $xml = Get-Content -Path $taskXmlPath -Raw
    $xml = $xml -replace '<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>', '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
    $xml = $xml -replace '<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>', '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>'
    Set-Content -Path $taskXmlPath -Value $xml -Encoding Unicode
    & schtasks.exe /create /tn $TaskName /xml $taskXmlPath /f 2>&1 | Out-Null
    $xmlExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $prevPref
    if (Test-Path $taskXmlPath) { Remove-Item -Force $taskXmlPath }
}
if ($xmlExit -ne 0) {
    Write-Output "[WARN] could not re-register the task from XML (exit $xmlExit); it may be skipped while on battery."
}
else {
    Ok 'battery restrictions cleared (the task runs on battery too)'
}

# ---- 4) verify the task actually runs and logs -------------------------------
$before = 0
if (Test-Path $logFile) { $before = @(Get-Content $logFile -ErrorAction SilentlyContinue).Count }

Step 'verifying the task really runs (triggering it once)'
& schtasks.exe /run /tn $TaskName 2>&1 | Out-Null

$deadline = (Get-Date).AddSeconds(120)
$after = $before
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if (Test-Path $logFile) {
        $after = @(Get-Content $logFile -ErrorAction SilentlyContinue).Count
        if ($after -gt $before) { break }
    }
}

if ($after -le $before) {
    Fail "the task ran but wrote no log line within 120s. Inspect: schtasks /query /tn `"$TaskName`" /v /fo LIST   and   $logFile"
}

$last = (Get-Content $logFile | Select-Object -Last 1)
Ok 'task verified - last log line:'
Write-Output "       $last"

if ($last -notmatch '\sOK\s') {
    Fail "the newest log line is not an OK line - the task is running but failing. Check network/credentials to GitHub."
}

Write-Output ''
Ok 'auto-sync is installed and verified'
Write-Output "  interval : every $IntervalMinutes minute(s)"
Write-Output "  log      : $logFile"
Write-Output "  run now  : schtasks /run /tn `"$TaskName`"   (or: powershell -File `"$syncPs1`")"
Write-Output "  remove   : powershell -File `"$PSCommandPath`" -Uninstall"
Write-Output "  skills   : $DshHome\skills (DSH hot-discovers changes; no restart needed)"
exit 0
