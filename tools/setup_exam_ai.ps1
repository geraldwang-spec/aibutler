param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv-exam-ai/Scripts/python.exe')) {
    & $Python -m venv .venv-exam-ai
    if ($LASTEXITCODE -ne 0) { throw '建立 CPU 模型環境失敗，請使用 Python 3.12。' }
}
& ./.venv-exam-ai/Scripts/python.exe -m pip install -r requirements-exam-ai.txt
if ($LASTEXITCODE -ne 0) { throw 'CPU 模組套件安裝失敗。' }
& ./.venv-exam-ai/Scripts/python.exe tools/download_exam_models.py
if ($LASTEXITCODE -ne 0) { throw '模型下載失敗。' }
Write-Host 'CPU 模型已下載；沒有執行推論或測試。'
