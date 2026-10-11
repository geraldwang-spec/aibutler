$env:APP_MODE = "dev"
$env:DB_TYPE = "sqlite"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
python app.py
