# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Runs the cross-model evaluation (python -m components.context_bench.evaluate) with the
# backend venv's Python from the Smart Classroom root: performance and accuracy of the INT4
# Qwen3-VL-8B-Instruct, Qwen3.5-9B, Qwen3.6-35B-A3B (DFlash off and on) and Qwen3.8-27B, then
# one Markdown report. Every argument is forwarded; its exit code (0 ok, 1 failed/partial
# cases, 2 invalid arguments, 130 Ctrl-C) is this script's exit code.
#
# Usage:
#   .\components\context_bench\run_evaluation.ps1 --list-profiles
#   .\components\context_bench\run_evaluation.ps1 --quick
#   .\components\context_bench\run_evaluation.ps1
#   .\components\context_bench\run_evaluation.ps1 --models qwen3.6-35b-a3b --dflash-k 3 5 7
#
# If PowerShell blocks local scripts, relax the policy for this process only:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }

# Two directories above this script: context_bench -> components -> app root
# (smart-classroom/Windows).
$SmartClassroomRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir '..\..')).ProviderPath
$VenvPath = Join-Path (Split-Path -Parent $SmartClassroomRoot) 'smartclassroom'
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host "Backend venv not found at $VenvPath." -ForegroundColor Red
    Write-Host "Prepare it first: $(Join-Path $SmartClassroomRoot 'setup-smart-classroom.ps1')" -ForegroundColor Yellow
    exit 2
}

$ExitCode = 1
Push-Location -LiteralPath $SmartClassroomRoot
try {
    & $VenvPython -m components.context_bench.evaluate @($args | ForEach-Object { [string]$_ })
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $ExitCode
