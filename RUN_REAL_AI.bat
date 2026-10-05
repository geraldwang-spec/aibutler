@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
)
echo Starting AI Butler with GROQ API providers...
echo Text AI: Groq API (one GROQ_API_KEY for all roles)
echo Local only: bge-m3 embedding for RAG
echo Model: qwen/qwen3.8-27b
echo.
python app.py
pause
