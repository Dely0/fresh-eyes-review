<#
.SYNOPSIS
    Pull fresh-eyes-review from GitHub and install the skill into this machine's
    global DSH skill root.

.DESCRIPTION
    DSH hot-discovers skills by scanning <DSH_HOME>/skills, so "installing" this
    skill is just "put the directory there". Doing that by hand is what makes the
    local copy drift from the published one: nothing tells you when it fell behind.

    This script closes that loop and is the single entry point for the Windows
    scheduled task (and for a human who wants "just get me up to date"):

      1) refuse to run twice at the same time (named mutex),
      2) clone the repo on first run, or `git pull --ff-only` when the working
         tree has no edits to tracked files,
      3) mirror <repo>/fresh-eyes-review/ into <DSH_HOME>/skills/fresh-eyes-review/
         and verify every copied file by SHA256,
      4) run the skill's own regression suite against the *installed* copy, so a
         bad pull cannot land silently,
      5) append one summary line to sync-fresh-eyes-review.log next to this script.

    The upstream layout matters: the skill lives in <repo>/fresh-eyes-review/, not
    at the repo root. Copying the repo root would nest one level too deep and DSH
    would stop finding SKILL.md.

    NOTE: this file is intentionally ASCII-only and LF-terminated. Windows
    PowerShell 5.1 decodes a BOM-less script as ANSI, so non-ASCII text would
    become mojibake and break parsing. Keep it ASCII.

.PARAMETER DshHome
    DSH home directory. Resolution order: this parameter, then $DSH_HOME, then
    ~/.dsh. The last fallback exists because a Windows scheduled task does not
    inherit $DSH_HOME (the DSH launcher sets it only inside its own process tree).

.PARAMETER RepoPath
    Where the working clone lives. Default: <DSH_HOME>/tmp/fresh-eyes-review-repo.

.PARAMETER Remote
    Upstream URL. Default: https://github.com/Dely0/fresh-eyes-review.git

.PARAMETER Branch
    Branch to track. Default: main.

.PARAMETER NoPull
    Skip the fetch/pull and only re-verify and re-copy from the local clone.

.PARAMETER NoTest
    Skip step 4 (the installed copy's regression suite). Faster, but a broken
    pull can then land unnoticed.

.PARAMETER DryRun
    Report what would be copied without writing into the skills root.

.PARAMETER Quiet
    Only the log line is written to stdout.

.EXAMPLE
    powershell -NoProfile -File scripts/sync-skill.ps1
    Normal run: pull, copy, verify, test.

.EXAMPLE
    powershell -NoProfile -File scripts/sync-skill.ps1 -DryRun
    Show what would change without touching the installed skill.

.NOTES
    Exit code: 0 = installed and verified (or already up to date); 1 = pull, copy,
    hash verification, or the regression suite failed. Every run appends exactly
    one line to sync-fresh-eyes-review.log. Writes only under <DSH_HOME>/skills,
    <RepoPath>, and that log.
#>
[CmdletBinding()]
param(
    [string] $DshHome = $env:DSH_HOME,
    [string] $RepoPath,
    [string] $Remote = 'https://github.com/Dely0/fresh-eyes-review.git',
    [string] $Branch = 'main',
    [switch] $NoPull,
    [switch] $NoTest,
    [switch] $DryRun,
    [switch] $Quiet
)

$ErrorActionPreference = 'Stop'

$logFile = Join-Path $PSScriptRoot 'sync-fresh-eyes-review.log'
$skillName = 'fresh-eyes-review'

# ---- resolve DSH home the way DSH does -------------------------------------
# A scheduled task does NOT inherit $DSH_HOME: the DSH launcher sets that
# variable only inside its own process tree. Without this fallback the script
# would die before it could even write a log line - which looks exactly like
# "the task never ran".
if (-not $DshHome) { $DshHome = $env:DSH_HOME }
if (-not $DshHome -or -not $DshHome.Trim()) {
    $homePath = $env:USERPROFILE
    if (-not $homePath) { $homePath = [Environment]::GetFolderPath('UserProfile') }
    if (-not $homePath) {
        Write-Output 'result: FAILED - cannot resolve ~/.dsh; pass -DshHome <path>'
        exit 1
    }
    $DshHome = Join-Path $homePath '.dsh'
}
$DshHome = $DshHome.Trim()
if (-not (Test-Path $DshHome)) {
    Write-Output "result: FAILED - DSH home does not exist: $DshHome"
    exit 1
}
if (-not (Test-Path (Join-Path $DshHome 'skills')) -and
    -not (Test-Path (Join-Path $DshHome 'profiles'))) {
    Write-Output "result: FAILED - $DshHome does not look like a DSH home (no skills/ or profiles/ inside)"
    exit 1
}

if (-not $RepoPath -or -not $RepoPath.Trim()) {
    $RepoPath = Join-Path (Join-Path $DshHome 'tmp') 'fresh-eyes-review-repo'
}
$RepoPath = $RepoPath.Trim()

$skillsRoot = Join-Path $DshHome 'skills'
$target     = Join-Path $skillsRoot $skillName
$source     = Join-Path $RepoPath $skillName

# git must never block on an interactive prompt: a scheduled task has no console.
$env:GIT_TERMINAL_PROMPT = '0'
$env:GIT_ASKPASS = ''
$env:SSH_ASKPASS = ''

function Write-Log {
    param([Parameter(Mandatory)][string] $Line)
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $logFile -Value "$stamp $Line" -Encoding UTF8
}

# Run a native command and return ONLY its exit code.
#
# Why this exists: git writes progress and "From <url>" to STDERR, and with
# $ErrorActionPreference = 'Stop' Windows PowerShell 5.1 turns any stderr line
# from a native command into a TERMINATING error ("NativeCommandError"). So
# `& git fetch ... 2>&1 | Out-Null` does not merely fail - it aborts the whole
# run inside the fetch line and the catch block reports a misleading message.
# The only safe shape is to relax the preference around the native call and
# branch on the exit code ourselves.
function Invoke-Native {
    param(
        [Parameter(Mandatory)][string] $FilePath,
        [Parameter(Mandatory)][string[]] $Arguments
    )
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $FilePath @Arguments 2>&1 | Out-Null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Get-ShortRev {
    param([string] $Path)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        return (@(& git -C $Path rev-parse --short HEAD 2>$null) | Select-Object -First 1)
    }
    finally { $ErrorActionPreference = $previous }
}

# GitHub connectivity from this network is intermittent: measured 1 failure in 5
# back-to-back `git ls-remote` calls, each failing with "Failed to connect to
# github.com port 443 after 21s". Treating the first failure as fatal makes the
# scheduled task report FAIL for what is really a blip - and that noise buries
# the failures that ARE real.
#
# Retries only help for transient errors. Authentication and missing-repo errors
# are permanent, so they fail on the first attempt instead of stalling.
function Test-TransientGitError {
    param([string] $Message)
    if (-not $Message) { return $true }   # unknown: give it one more chance
    $permanent = 'Authentication failed', 'could not read Username',
                 'Permission denied', 'Repository not found', 'not found',
                 'terminal prompts disabled'
    foreach ($marker in $permanent) {
        if ($Message -like "*$marker*") { return $false }
    }
    return $true
}

function Invoke-GitWithRetry {
    param(
        [Parameter(Mandatory)][string] $Context,
        [Parameter(Mandatory)][string[]] $Arguments,
        [int] $Attempts = 3,
        [int] $DelaySeconds = 3
    )
    $lastMessage = ''
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $previous = $ErrorActionPreference
        $output = $null
        try {
            $ErrorActionPreference = 'Continue'
            $output = & git @Arguments 2>&1
            $code = $LASTEXITCODE
        }
        finally { $ErrorActionPreference = $previous }

        if ($code -eq 0) {
            if ($attempt -gt 1) {
                Write-Output "  [$Context] succeeded on attempt $attempt/$Attempts (previous attempts failed transiently)"
            }
            return 0
        }

        $lastMessage = (($output | Out-String).Trim() -split "`n" | Select-Object -First 1)
        if (-not (Test-TransientGitError -Message $lastMessage)) {
            throw "$Context failed with a permanent error (exit $code): $lastMessage"
        }
        if ($attempt -lt $Attempts) {
            Write-Output "  [$Context] attempt $attempt/$Attempts failed (transient): $lastMessage"
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    throw "$Context failed after $Attempts attempts (exit $code): $lastMessage"
}

# Single instance: a slow pull must not overlap the next scheduled tick.
$mutex = New-Object System.Threading.Mutex($false, 'Local\fresh-eyes-review-sync')
$held = $false
try { $held = $mutex.WaitOne(0) }
catch [System.Threading.AbandonedMutexException] { $held = $true }
if (-not $held) {
    Write-Log 'SKIP another sync is already running'
    if (-not $Quiet) { Write-Output 'another sync is already running; nothing to do' }
    exit 0
}

$pullState = 'skipped'
$revBefore = ''
$revAfter  = ''
$copied    = 0
$verified  = 0
$testState = 'skipped'

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'git is not on PATH; cannot pull the repository.'
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'python is not on PATH; cannot verify the installed copy.'
    }

    # ---- 1) get the working clone up to date -------------------------------
    if (-not (Test-Path (Join-Path $RepoPath '.git'))) {
        if (Test-Path $RepoPath) { Remove-Item -Recurse -Force $RepoPath }
        $parent = Split-Path -Parent $RepoPath
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        $code = Invoke-Native 'git' @('clone', '--branch', $Branch, '--depth', '1', $Remote, $RepoPath)
        if ($code -ne 0) { throw "git clone failed (exit $code)" }
        $pullState = 'cloned'
        $revAfter = Get-ShortRev $RepoPath
    }
    elseif ($NoPull) {
        $pullState = 'skipped (NoPull)'
        $revAfter = Get-ShortRev $RepoPath
    }
    else {
        $revBefore = Get-ShortRev $RepoPath
        $previous = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            # Only real edits to TRACKED files block a pull. Untracked files are
            # none of this script's business and would otherwise freeze the clone.
            $dirty = @(& git -C $RepoPath status --porcelain --untracked-files=no 2>$null)
        }
        finally { $ErrorActionPreference = $previous }

        if ($dirty.Count -gt 0) {
            $pullState = "skipped (dirty tree: $($dirty.Count) path(s))"
        }
        else {
            Invoke-GitWithRetry -Context 'git fetch' -Arguments @('-C', $RepoPath, 'fetch', '--prune', 'origin') | Out-Null
            Invoke-GitWithRetry -Context 'git pull' -Arguments @('-C', $RepoPath, 'pull', '--ff-only') | Out-Null
            $revAfter = Get-ShortRev $RepoPath
            $pullState = if ($revBefore -eq $revAfter) { 'up-to-date' } else { "updated $revBefore -> $revAfter" }
        }
    }

    if (-not (Test-Path $source)) {
        throw "the clone has no $skillName/ directory at its root; upstream layout changed?"
    }

    # ---- 2) mirror the skill into the skills root --------------------------
    $sourceFiles = @(Get-ChildItem $source -Recurse -File |
        Sort-Object { $_.FullName.Substring($source.Length) })

    if ($DryRun) {
        foreach ($file in $sourceFiles) {
            $rel = $file.FullName.Substring($source.Length).TrimStart('\')
            $dest = Join-Path $target $rel
            $state = 'new'
            if (Test-Path $dest) {
                $state = if ((Get-FileHash $file.FullName -Algorithm SHA256).Hash -eq
                             (Get-FileHash $dest -Algorithm SHA256).Hash) { 'same' } else { 'CHANGED' }
            }
            Write-Output ("  {0,-10} {1}" -f $state, $rel)
        }
        Write-Log "DRYRUN pull=$pullState files=$($sourceFiles.Count) rev=$revAfter"
        Write-Output "result: DRY RUN ($($sourceFiles.Count) file(s) would be mirrored, pull=$pullState)"
        exit 0
    }

    if (-not (Test-Path $skillsRoot)) { New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null }
    if (-not (Test-Path $target)) { New-Item -ItemType Directory -Force -Path $target | Out-Null }

    foreach ($file in $sourceFiles) {
        $rel = $file.FullName.Substring($source.Length).TrimStart('\')
        $dest = Join-Path $target $rel
        $destDir = Split-Path -Parent $dest
        if ($destDir -and -not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        if ((Test-Path $dest) -and
            (Get-FileHash $file.FullName -Algorithm SHA256).Hash -eq
            (Get-FileHash $dest -Algorithm SHA256).Hash) {
            $verified++
            continue
        }
        Copy-Item -Path $file.FullName -Destination $dest -Force
        $copied++
    }

    # Files removed upstream must stop being installed, or the local copy keeps
    # running code the repo no longer publishes. Stale __pycache__ is not a
    # difference worth reporting.
    $stale = @()
    foreach ($existing in @(Get-ChildItem $target -Recurse -File)) {
        $rel = $existing.FullName.Substring($target.Length).TrimStart('\')
        if ($rel -match '__pycache__') { continue }
        if (-not (Test-Path (Join-Path $source $rel))) { $stale += $existing }
    }
    foreach ($file in $stale) { Remove-Item -Force $file.FullName }

    # ---- 3) verify what actually landed ------------------------------------
    foreach ($file in $sourceFiles) {
        $rel = $file.FullName.Substring($source.Length).TrimStart('\')
        $dest = Join-Path $target $rel
        if (-not (Test-Path $dest)) { throw "verification failed: $rel is missing after copy" }
        if ((Get-FileHash $file.FullName -Algorithm SHA256).Hash -ne
            (Get-FileHash $dest -Algorithm SHA256).Hash) {
            throw "verification failed: $rel differs after copy"
        }
        $verified++
    }

    # ---- 4) the installed copy must pass its own suite ---------------------
    if (-not $NoTest) {
        $suite = Join-Path $target 'scripts\test_check_review_report.py'
        if (Test-Path $suite) {
            $env:PYTHONIOENCODING = 'utf-8'
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $previous = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $suiteOut = & python $suite 2>&1
                $suiteExit = $LASTEXITCODE
            }
            finally { $ErrorActionPreference = $previous }
            if ($suiteExit -ne 0) {
                $tail = ($suiteOut | Select-Object -Last 1)
                throw "the installed copy failed its own regression suite (exit $suiteExit): $tail"
            }
            $testState = 'passed'
        }
        else {
            $testState = 'no-suite'
        }
    }

    Write-Log "OK pull=$pullState rev=$revAfter copied=$copied verified=$verified stale=$($stale.Count) test=$testState"
    if (-not $Quiet) {
        Write-Output "result: OK (pull=$pullState, $verified file(s) verified, copied=$copied, removed=$($stale.Count), test=$testState)"
        Write-Output "installed to: $target"
    }
    exit 0
}
catch {
    Write-Log "FAIL $($_.Exception.Message)"
    Write-Output "result: FAILED - $($_.Exception.Message)"
    exit 1
}
finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
