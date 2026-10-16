# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Explicitly prepares the Python environment the context benchmark needs, without running
# the full interactive setup-smart-classroom.ps1. Creates (or reuses) the shared backend venv
# at <smart-classroom>/../smartclassroom and installs the reviewed, exactly pinned packages
# in requirements.txt beside this script. Setup never runs during planning or trials.
#
# TLS verification is never weakened and no trusted host or extra index is added; the
# requirements file is rejected unless every requirement is an exact `name==version` pin.
#
# Usage (from anywhere; paths resolve from this script's location):
#   .\components\context_bench\setup_env.ps1
#
# If PowerShell blocks local scripts, relax the policy for this process only:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }

# Two directories above this script: context_bench -> components -> smart-classroom.
$SmartClassroomRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir '..\..')).ProviderPath
$VenvPath = Join-Path (Split-Path -Parent $SmartClassroomRoot) 'smartclassroom'
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'
$RequirementsPath = Join-Path $ScriptDir 'requirements.txt'

if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
    Write-Host "[ERROR] Missing $RequirementsPath" -ForegroundColor Red
    exit 2
}

# Accept only comments, blank lines and exact pins (optionally with an environment marker).
$PinPattern = '^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.+!_-]*(\s*;\s*[^#]+)?$'
$LineNumber = 0
foreach ($Line in Get-Content -LiteralPath $RequirementsPath) {
    $LineNumber++
    $Text = $Line.Trim()
    if ($Text -eq '' -or $Text.StartsWith('#')) { continue }
    if ($Text -notmatch $PinPattern) {
        Write-Host "[ERROR] requirements.txt line ${LineNumber} is not an exact name==version pin: $Text" -ForegroundColor Red
        exit 2
    }
}

if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    Write-Host "[OK] Backend venv already exists at $VenvPath" -ForegroundColor Green
}
else {
    $SystemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $SystemPython) {
        Write-Host "[ERROR] python (3.12) is not on PATH; install it or run setup-smart-classroom.ps1" -ForegroundColor Red
        exit 2
    }
    Write-Host "Creating backend venv at $VenvPath ..." -ForegroundColor Yellow
    & $SystemPython.Source -m venv $VenvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Write-Host "[ERROR] Failed to create the venv" -ForegroundColor Red
        exit 2
    }
}

Write-Host "Installing pinned context_bench requirements into $VenvPath ..." -ForegroundColor Yellow
& $VenvPython -m pip install --no-input --disable-pip-version-check -r $RequirementsPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed -- see the output above" -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "[OK] Environment ready. Check the plan with:" -ForegroundColor Green
Write-Host "  .\components\context_bench\run_benchmark.ps1 --list-profiles"
exit 0
