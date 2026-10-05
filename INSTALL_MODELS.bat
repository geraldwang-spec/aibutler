@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo AI Butler CPU helper model installer
echo E5 / NLI / OCR run on CPU. Groq settings remain unchanged.
echo No local LLM or voice model will be downloaded.
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_exam_ai.ps1
if errorlevel 1 exit /b 1
pause
