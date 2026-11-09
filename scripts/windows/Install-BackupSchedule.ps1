#Requires -Version 5.1
<# Daily encrypted ledger backup plus a restore drill, as the current user.
   First seal the passphrase once in an interactive console:  uv run gymctl key set-backup
   The scheduled run never sees the passphrase in arguments, environment or history; DPAPI unseals it.
   Remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Ledger,
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$CoreDirectory,
    [string]$At = '03:17',
    [ValidateRange(2, 365)][int]$Keep = 7,
    [string]$TaskName = 'TradingGYM Backup',
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $CoreDirectory) { $CoreDirectory = Join-Path $PSScriptRoot '..\..\gym-core' }

if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    return
}
$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$uv = (Get-Command uv -ErrorAction Stop).Source
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
# Backup first, then prove the newest bundle restores; either failure fails the task run.
$command = "& '$uv' run gymctl backup-once '$Ledger' '$Destination' --keep $Keep --stored-passphrase; if (`$LASTEXITCODE) { exit `$LASTEXITCODE }; " +
           "& '$uv' run gymctl restore-drill '$Destination' --stored-passphrase; exit `$LASTEXITCODE"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -Command `"$command`"" -WorkingDirectory $core
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register daily backup of $Ledger to $Destination at $At")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$TaskName'. Results appear on the Backups page after each run."
}
