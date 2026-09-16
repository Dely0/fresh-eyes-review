#!/usr/bin/env pwsh
# Evidence probe: the handoff trade-off "provenance" test is a bare substring
# match over the raw line, so a trade-off entry that explicitly says it has NO
# human decision behind it still satisfies the check -- and the gate reports the
# handoff as compliant under --strict.
#
# Prints F6_NEGATED_PROVENANCE_PASSES and exits 1 when the gate accepts it.
$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"
$gate = $args[0]

$dir = Join-Path ([System.IO.Path]::GetTempPath()) ("fer-f6-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path (Join-Path $dir "src"), (Join-Path $dir "ev") | Out-Null

$handoff = @'
# 审查交接文档

## 范围
- 工作目录：`C:\work\repo`

## 已定取舍
- 不要报归一化产生的假不一致 | 依据：未经 HumanDecision 确认，是本轮执行者自行决定 | 影响边界：无
'@
Set-Content -Encoding utf8 (Join-Path $dir ".review-handoff.md") $handoff

$report = @'
### F1 兜底 · 严重度：高
- 位置：src/real.py:1
- 复现：python -c "print('checked=1')"
- 证据文件：ev/F1.txt
- 反向前置：python -c "import sys;sys.exit(1)"
- 反向前置证据：ev/R1.txt
- 实测：见证据文件
'@
Set-Content -Encoding utf8 (Join-Path $dir "report.md") $report
Set-Content -Encoding ascii (Join-Path $dir "src\real.py") "x = 1"
Set-Content -Encoding ascii (Join-Path $dir "ev\F1.txt") "[exit code: 0]`nchecked=1"
Set-Content -Encoding ascii (Join-Path $dir "ev\R1.txt") "[exit code: 1]`nfail"

Push-Location $dir
& python $gate --strict --handoff .review-handoff.md report.md
$code = $LASTEXITCODE
Pop-Location
Write-Host "gate exit=$code"
Select-String -Path (Join-Path $dir ".review-handoff.md") -Pattern "HumanDecision" | ForEach-Object { "匹配行: " + $_.Line }
if ($code -eq 0) {
    Write-Host "F6_NEGATED_PROVENANCE_PASSES: 条目自称「未经 HumanDecision 确认」，--strict 下仍被判为有出处"
    exit 1
}
Write-Host "F6_NEGATED_PROVENANCE_REJECTED"
exit 0
