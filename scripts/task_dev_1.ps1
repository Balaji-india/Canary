# The review-task screen, batch task-dev-1 (plan: docs/plans/review_task_screen.md).
# Safe to run again after an interruption: calibrate --resume skips finished slots and reaudit skips reviewed runs.
# Progress goes to data/runs/campaign.log (written by the commands themselves).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = ".venv\Scripts\python.exe"
$batch = "task-dev-1"

if (Test-Path "data\sealed_plans\$batch.json") {
    & $python -m canary.cli calibrate --batch $batch --resume
} else {
    & $python -m canary.cli calibrate --runs 40 --batch $batch --seed 1108
}
if ($LASTEXITCODE -ne 0) { Write-Output "calibrate stopped (exit $LASTEXITCODE); run this script again to resume"; exit 1 }

# Cheapest models first, llama3.1:8b (partly on the CPU) last.
$roles = @("skeptic_a_grounded", "skeptic_a_checklist", "skeptic_b", "skeptic_b_grounded", "skeptic_b_checklist",
           "skeptic_c", "skeptic_c_grounded", "skeptic_c_checklist")
foreach ($role in $roles) {
    & $python -m canary.cli reaudit --batch $batch --role $role
    if ($LASTEXITCODE -ne 0) { Write-Output "reaudit $role stopped (exit $LASTEXITCODE); run this script again to resume"; exit 1 }
}
Write-Output "task-dev-1 finished. Next: python -m eval.compare_tasks --batch $batch"
