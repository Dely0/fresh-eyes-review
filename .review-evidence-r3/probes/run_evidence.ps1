# Run the reverse-precondition probes and record their raw output as evidence
# files under .review-evidence-r3/, with the exit code as the mandatory first line.
$ErrorActionPreference = "Continue"
$repo = "C:\Users\dupenglai\.dsh\tmp\fer-repo"
$out = Join-Path $repo ".review-evidence-r3"
$ver = "C:\Users\dupenglai\AppData\Local\Temp\fer-verify-r3"
$gate = Join-Path $repo "fresh-eyes-review\scripts\check_review_report.py"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONIOENCODING = "utf-8"

function Capture([string]$file, [scriptblock]$body) {
    $text = & $body 2>&1 | Out-String
    $code = $LASTEXITCODE
    $lines = @("[exit code: $code]") + ($text -split "`r?`n")
    Set-Content -Path $file -Value $lines -Encoding utf8
    Write-Host "$file  -> exit $code"
}

Capture (Join-Path $out "F1-reverse.txt") { & python "$ver\f1_probe.py" $gate }
Capture (Join-Path $out "F3-reverse.txt") { & python "$ver\f3_probe.py" }
Capture (Join-Path $out "F4-reverse.txt") { & python "$ver\f4_probe.py" $gate }
Capture (Join-Path $out "F5-reverse.txt") { & python "$ver\f5b_probe.py" $gate }
Capture (Join-Path $out "F6-reverse.txt") { & pwsh -NoProfile -File "$ver\f6_probe.ps1" $gate }
