# Re-capture: run each probe directly (no -File wrapper) in the repo, so the
# recorded evidence is the probe's own raw stdout/stderr plus its exit code.
$ErrorActionPreference = "Continue"
$repo = "C:\Users\dupenglai\.dsh\tmp\fer-repo"
$out = Join-Path $repo ".review-evidence-r3"
$ver = "C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3"
$gate = Join-Path $repo "fresh-eyes-review\scripts\check_review_report.py"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONIOENCODING = "utf-8"

function Capture([string]$file, [scriptblock]$body) {
    $text = & $body 2>&1 | Out-String
    $code = $LASTEXITCODE
    $lines = @("[exit code: $code]") + ($text -split "`r?`n")
    Set-Content -Path $file -Value $lines -Encoding utf8
    Write-Host "$file  -> exit $code"
}

Push-Location $repo
Capture (Join-Path $out "F1-probe.txt")  { & python "$ver\f1_probe.py" $gate }
Capture (Join-Path $out "F3-probe.txt")  { & python "$ver\f3_probe.py" }
Capture (Join-Path $out "F4-probe.txt")  { & python "$ver\f4_probe.py" $gate }
Capture (Join-Path $out "F5-probe.txt")  { & python "$ver\f5b_probe.py" $gate }
Capture (Join-Path $out "F6-probe.txt")  { & pwsh -NoProfile -File "$ver\f6_probe.ps1" $gate }
Capture (Join-Path $out "F7-probe.txt")  { & python "$ver\f7_probe.py" $gate }
Pop-Location
