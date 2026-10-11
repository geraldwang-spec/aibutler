@echo off
setlocal
cd /d "%~dp0"
set APP_MODE=dev
set DB_TYPE=sqlite
if not exist ".env" copy /y ".env.example" ".env" >nul
python app.py
endlocal
pause
