# Weekly run (guide Step 6.3): collect -> analyze -> recommend -> report.
#
# Run it from anywhere: it moves to the repository root and uses its .venv and .env.
# Every step runs even if an earlier one reported failures (a blocked or broken source
# should not stop the summary); the script exits with 1 if any step failed, so a
# scheduler can flag the run.
#
# To schedule later on Windows (Task Scheduler), for example Mondays at 08:00:
#   schtasks /Create /TN "Scout AI weekly" /SC WEEKLY /D MON /ST 08:00 `
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File <repo>\scripts\weekly.ps1"
# The database must be reachable at that time (Docker running for the local one).

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$scout = Join-Path (Get-Location) ".venv\Scripts\scout.exe"

$failed = @()
foreach ($step in @("collect", "analyze", "recommend", "report")) {
    Write-Output "== scout $step ($(Get-Date -Format s))"
    & $scout $step
    if ($LASTEXITCODE -ne 0) { $failed += $step }
}

if ($failed.Count -gt 0) {
    Write-Output "Failed steps: $($failed -join ', ')"
    exit 1
}
