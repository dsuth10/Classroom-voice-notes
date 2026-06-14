<#
.SYNOPSIS
    Ensures that all PowerShell scripts in the .specify directory are executable.
.DESCRIPTION
    This script checks for .ps1 files in the .specify/scripts/ps directory and 
    attempts to set their execution policy or unblock them if necessary.
#>

$scriptDir = Join-Path $PSScriptRoot "..\.specify\scripts\ps"

if (Test-Path $scriptDir) {
    Write-Host "Checking PowerShell scripts in $scriptDir..."
    $scripts = Get-ChildItem -Path $scriptDir -Filter *.ps1 -Recurse
    
    foreach ($script in $scripts) {
        Write-Host "Unblocking $($script.FullName)..."
        Unblock-File -Path $script.FullName -ErrorAction SilentlyContinue
    }
} else {
    Write-Warning "Directory $scriptDir not found."
}
