param([Parameter(Mandatory=$true)][string]$Destination, [string]$Database)
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    throw "Backup destination does not exist: $Destination"
}
if ($Database) { $env:EXPENSE_DB_PATH = $Database }
& py (Join-Path $scriptDir 'backup_db.py') --destination $Destination --daily
if ($LASTEXITCODE -ne 0) { throw "Expense backup failed with exit code $LASTEXITCODE" }
