# Starts the RX3000 backend (port 8177) and frontend (port 5180) in two windows.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# --reload, because without it this served September's code all day.
#
# The frontend reloads on every save and the backend did not, so an afternoon
# went into "bugs" that were the running process being hours out of date: a
# fix was made, the screen was refreshed, nothing changed, and the search went
# looking for a second fault that did not exist. The cost of watching the
# files is nothing on a development machine. The cost of not watching them was
# most of a day.
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m uvicorn app.main:app --port 8177 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host "RX3000 starting..."
Write-Host "  Backend : http://localhost:8177  (reloads on save)"
Write-Host "  Frontend: http://localhost:5180  (open this in your browser)"
