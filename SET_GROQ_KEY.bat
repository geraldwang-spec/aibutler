@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".env" copy /y ".env.example" ".env" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='.env'; $secure=Read-Host 'Paste Groq API Key' -AsSecureString; $b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); try{$k=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)} finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)}; $c=Get-Content $p -Raw; if($c -match '(?m)^GROQ_API_KEY='){ $c=[regex]::Replace($c,'(?m)^GROQ_API_KEY=.*$','GROQ_API_KEY='+$k) } else { $c += [Environment]::NewLine+'GROQ_API_KEY='+$k+[Environment]::NewLine }; Set-Content -Path $p -Value $c -Encoding UTF8; Write-Host 'Groq key saved to .env (not echoed).'"
if errorlevel 1 (
  echo Failed to update .env
  pause
  exit /b 1
)
echo Done.
pause
