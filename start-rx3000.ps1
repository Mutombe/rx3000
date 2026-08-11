# Starts the RX3000 backend (port 8177) and frontend (port 5180) in two windows.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m uvicorn app.main:app --port 8177"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host "RX3000 starting..."
Write-Host "  Backend : http://localhost:8177"
Write-Host "  Frontend: http://localhost:5180  (open this in your browser)"
