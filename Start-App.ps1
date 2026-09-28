[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendPython = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$frontend = Join-Path $projectRoot 'frontend'

function Stop-WithMessage([string]$message) {
    Write-Host "`nSTART NOT COMPLETED" -ForegroundColor Red
    Write-Host $message -ForegroundColor Yellow
    exit 1
}

try {
    if (-not (Test-Path -LiteralPath $backendPython)) { Stop-WithMessage 'Backend dependencies are not installed. Run Update-App.ps1 first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules'))) { Stop-WithMessage 'Frontend dependencies are not installed. Run Update-App.ps1 first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'backend\.env'))) { Stop-WithMessage 'backend/.env is missing. Copy backend/.env.example to backend/.env and add your Gemini key.' }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Stop-WithMessage 'npm was not found. Install Node.js 20 or newer, then try again.' }

    $backendCommand = "Set-Location -LiteralPath '$projectRoot\backend'; & '$backendPython' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
    $frontendCommand = "Set-Location -LiteralPath '$frontend'; npm run dev"
    Start-Process powershell.exe -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $backendCommand)
    Start-Process powershell.exe -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $frontendCommand)
    Write-Host 'Recipe Reel Studio is starting in two PowerShell windows.' -ForegroundColor Green
    Write-Host 'Open the local address printed by the frontend window (usually http://localhost:3000).'
} catch {
    Stop-WithMessage $_.Exception.Message
}
