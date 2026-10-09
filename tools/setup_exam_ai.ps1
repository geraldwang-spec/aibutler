param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv-exam-ai/Scripts/python.exe')) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv --python 3.12 --allow-existing .venv-exam-ai
    } else {
        & $Python -m venv .venv-exam-ai
    }
    if ($LASTEXITCODE -ne 0) { throw '建立 CPU 模型環境失敗，請使用 Python 3.12。' }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv pip install --python .venv-exam-ai/Scripts/python.exe -r requirements-exam-ai.txt
} else {
    & ./.venv-exam-ai/Scripts/python.exe -m pip install -r requirements-exam-ai.txt
}
if ($LASTEXITCODE -ne 0) { throw 'CPU 模組套件安裝失敗。' }
& ./.venv-exam-ai/Scripts/python.exe tools/download_exam_models.py
if ($LASTEXITCODE -ne 0) { throw '模型下載失敗。' }
& ./.venv-exam-ai/Scripts/python.exe -X utf8 tools/check_exam_ai.py
if ($LASTEXITCODE -ne 0) { throw 'CPU 實際推論檢查失敗；請查看上方訊息。' }
Write-Host 'E5、NLI 與 OCR 已通過 CPU 推論檢查。'
