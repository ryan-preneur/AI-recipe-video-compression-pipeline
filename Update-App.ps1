[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Stop-WithMessage([string]$message) {
    Write-Host "`nUPDATE NOT COMPLETED" -ForegroundColor Red
    Write-Host $message -ForegroundColor Yellow
    exit 1
}

function Find-Python {
    foreach ($candidate in @(
        (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'),
        'py',
        'python'
    )) {
        if ($candidate -like '*\\*') {
            if (Test-Path -LiteralPath $candidate) { return ,@($candidate) }
        } elseif (Get-Command $candidate -ErrorAction SilentlyContinue) {
            if ($candidate -eq 'py') { return ,@('py', '-3') }
            return ,@('python')
        }
    }
    Stop-WithMessage 'Python 3.11 or newer was not found. Install it, then run Update-App.ps1 again.'
}

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-WithMessage 'Git is not installed or is not on PATH. Install Git for Windows, reopen PowerShell, and try again.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.git'))) {
        Stop-WithMessage 'This folder is not connected to Git yet. Follow the one-time Git setup in README.md first.'
    }
    $remote = git remote get-url origin 2>$null
    if (-not $remote) {
        Stop-WithMessage 'No Git remote named origin is configured. Follow the one-time private GitHub setup in README.md first.'
    }
    $branch = git branch --show-current
    if (-not $branch) { Stop-WithMessage 'Git is in detached-HEAD mode. Switch back to your main branch, then try again.' }
    $upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
    if (-not $upstream) { Stop-WithMessage "Branch '$branch' has no remote tracking branch. Follow the README setup, then try again." }
    if (git status --porcelain --untracked-files=no) {
        Stop-WithMessage 'You have uncommitted app-code changes. Commit or stash them before updating so Git cannot overwrite your work. Your private .env files and backend/data are ignored and safe.'
    }

    $before = git rev-parse HEAD
    Write-Host "Checking for updates on $branch..." -ForegroundColor Cyan
    git fetch origin
    $target = git rev-parse '@{u}'
    if ($before -ne $target) {
        git merge --ff-only '@{u}'
        Write-Host 'App files updated.' -ForegroundColor Green
    } else {
        Write-Host 'App files are already up to date.' -ForegroundColor Green
    }

    $changed = if ($before -ne $target) { @(git diff --name-only $before $target) } else { @() }
    $backendVenv = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
    $createdVenv = -not (Test-Path -LiteralPath $backendVenv)
    $python = if (Test-Path -LiteralPath $backendVenv) { ,@($backendVenv) } else { Find-Python }
    if ($createdVenv) {
        Write-Host 'Creating the backend virtual environment...' -ForegroundColor Cyan
        $pythonArguments = @($python | Select-Object -Skip 1) + @('-m', 'venv', (Join-Path $projectRoot 'backend\.venv'))
        & $python[0] @pythonArguments
        $python = ,@($backendVenv)
    }
    if ($createdVenv -or ($changed -contains 'backend/requirements.txt')) {
        Write-Host 'Installing changed backend dependencies...' -ForegroundColor Cyan
        $pythonArguments = @($python | Select-Object -Skip 1) + @('-m', 'pip', 'install', '-r', (Join-Path $projectRoot 'backend\requirements.txt'))
        & $python[0] @pythonArguments
    }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Stop-WithMessage 'npm was not found. Install Node.js 20 or newer, reopen PowerShell, and run this update again.'
    }
    $frontendModules = Join-Path $projectRoot 'frontend\node_modules'
    if (($changed -contains 'frontend/package-lock.json') -or ($changed -contains 'frontend/package.json') -or -not (Test-Path -LiteralPath $frontendModules)) {
        Write-Host 'Installing changed frontend dependencies...' -ForegroundColor Cyan
        Push-Location (Join-Path $projectRoot 'frontend')
        try { npm ci --cache .npm-cache } finally { Pop-Location }
    }
    Write-Host "`nUPDATE COMPLETE" -ForegroundColor Green
    Write-Host 'Your backend/.env, frontend/.env.local, and backend/data were left in this same folder.'
    Write-Host 'Run Start-App.bat (or .\Start-App.ps1) to launch the app.'
} catch {
    Stop-WithMessage $_.Exception.Message
}
