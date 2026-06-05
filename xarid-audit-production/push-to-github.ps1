param(
    [string]$RemoteUrl = 'https://github.com/XafizadinovUsnatdin/tenderai.git',
    [string]$Branch = 'main',
    [string]$CommitMessage = 'Add xarid-audit-production'
)

$ErrorActionPreference = 'Stop'

$repoRoot = git -C $PSScriptRoot rev-parse --show-toplevel
Set-Location $repoRoot

git checkout -B $Branch | Out-Null

$null = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    git remote set-url origin $RemoteUrl | Out-Null
} else {
    git remote add origin $RemoteUrl | Out-Null
}

git add xarid-audit-production

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host 'No changes to commit.'
    exit 0
}

git commit -m $CommitMessage | Out-Null
git push -u origin $Branch
