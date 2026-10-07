param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [string]$Database,
    [string]$At = '20:00'
)
$ErrorActionPreference = 'Stop'
$destinationPath = (Resolve-Path -LiteralPath $Destination -ErrorAction Stop).Path
$scriptPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'scheduled_backup.ps1'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $scriptPath + '" -Destination "' + $destinationPath + '"'
if ($Database) { $arguments += ' -Database "' + $Database + '"' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $At
Register-ScheduledTask -TaskName 'ExpenseTracker Daily Backup' -Action $action -Trigger $trigger `
    -Description 'Make one verified SQLite backup per day in the configured destination' -Force
Write-Host "Scheduled daily backups at $At to $destinationPath."
