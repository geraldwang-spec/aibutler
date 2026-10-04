@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ================================================================
echo AI Butler - REAL AI MODEL INSTALLER
echo ================================================================
echo Local downloads:
echo   1. qwen3.5:4b       - local classifier + fallback LLM
echo   2. bge-m3           - embedding / RAG / concept similarity
echo   3. Whisper large-v3 - speech to text
echo   4. Kokoro zh v1.1   - Mandarin text to speech
echo.
echo Cloud models (Groq) are NOT downloaded:
echo   qwen/qwen3.8-27b    - question generation / review
echo   openai/gpt-oss-120b - micro-course / tutor
echo.
echo If no GROQ_API_KEY is configured, the system automatically falls back
echo to local qwen3.5:4b for those roles.
echo ================================================================
echo.

python tools\setup_real_models.py
if errorlevel 1 (
  echo.
  echo [FAILED] Core model installation failed. Read the error above.
  pause
  exit /b 1
)

echo.
echo [OK] Real model setup finished.
echo Next: edit .env and add GROQ_API_KEY if you want Groq cloud models.
echo Then run RUN_REAL_AI.bat
pause
