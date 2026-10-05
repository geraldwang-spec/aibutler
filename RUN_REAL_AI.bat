@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
)
echo Starting AI Butler with GROQ API providers...
echo Text AI: Groq API (one GROQ_API_KEY for all roles)
echo Local only: CPU E5 / NLI; no Ollama fallback
echo Model: openai/gpt-oss-20b; output cap 800 tokens
echo.
python app.py
pause
