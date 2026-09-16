# Capture evidence for the two documentation-consistency probes (F7/F8 in the
# report) and for the handoff counting probe.
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
Capture (Join-Path $out "F8-doc-consistency.txt") { & python "$ver\f8_probe.py" }
Capture (Join-Path $out "F9-assertion-count.txt") { & python "$ver\f9_probe.py" }
Pop-Location
