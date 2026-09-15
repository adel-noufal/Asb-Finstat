# Starts ASB Finstat locally: FastAPI backend on :8000 + Vite frontend on :5173.
# Safe to re-run - already-running parts are skipped.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Backend venv missing. Run: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt'
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    throw 'Frontend deps missing. Run: cd frontend; npm install'
}
if (-not (Test-Path (Join-Path $root 'backend\.env'))) {
    Write-Warning 'backend\.env not found - copy backend\.env.example and set OPENROUTER_API_KEY, AI calls will fail without it.'
}

function Test-Port([int]$Port) {
    try { [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop) } catch { $false }
}

if (Test-Port 8000) {
    Write-Host 'Backend already listening on :8000 - skipping'
} else {
    $backend = Start-Process -PassThru -WorkingDirectory (Join-Path $root 'backend') $python `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'
    Write-Host "Backend starting (pid $($backend.Id))"
}

if (Test-Port 5173) {
    Write-Host 'Frontend already listening on :5173 - skipping'
} else {
    $frontend = Start-Process -PassThru -WorkingDirectory (Join-Path $root 'frontend') 'cmd' `
        -ArgumentList '/c', 'npm run dev'
    Write-Host "Frontend starting (pid $($frontend.Id))"
}

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and -not ((Test-Port 8000) -and (Test-Port 5173))) {
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Port 8000)) { Write-Warning 'Backend did not come up on :8000 - check its console window.' }
if (-not (Test-Port 5173)) { Write-Warning 'Frontend did not come up on :5173 - check its console window.' }

Write-Host ''
Write-Host 'Backend  : http://localhost:8000'
Write-Host 'Frontend : http://localhost:5173  <- open this'
