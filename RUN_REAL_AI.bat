@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
)
echo Starting AI Butler with REAL/HYBRID providers...
echo Local: qwen3.5:4b + bge-m3
echo Cloud when GROQ_API_KEY is set: qwen3.8-27b / gpt-oss-120b
echo.
python app.py
pause
