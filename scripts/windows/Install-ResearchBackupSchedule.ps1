#Requires -Version 5.1
<# Nightly encrypted backup of the research store (market.db, other stores, runs, raw segments) plus a restore drill.
   First seal the passphrase once in an interactive console:  uv run gymctl key set-backup
   Keep a copy of that passphrase off this machine: the DPAPI copy is lost with the laptop.
   -Destination: a folder on another drive, or a cloud-synced folder (Google Drive for desktop) with -AllowSameDevice.
   Preview with -WhatIf; remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$DataDirectory,
    [string]$CoreDirectory,
    [string]$At = '03:47',
    [ValidateRange(2, 365)][int]$Keep = 7,
    [switch]$AllowSameDevice,
    [string]$TaskName = 'TradingGYM Research Backup',
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $DataDirectory) { $DataDirectory = Join-Path $PSScriptRoot '..\..\data' }
if (-not $CoreDirectory) { $CoreDirectory = Join-Path $PSScriptRoot '..\..\gym-core' }

if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    return
}
$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$data = [IO.Path]::GetFullPath($DataDirectory)
$uv = (Get-Command uv -ErrorAction Stop).Source
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$same = if ($AllowSameDevice) { ' --allow-same-device' } else { '' }
# Back up, then prove the newest snapshot and the newest segments decrypt and verify; either failure fails the run.
$command = "& '$uv' run gymctl --data '$data' backup-research '$Destination' --keep $Keep --stored-passphrase$same; if (`$LASTEXITCODE) { exit `$LASTEXITCODE }; " +
           "& '$uv' run gymctl --data '$data' research-restore-drill '$Destination' --stored-passphrase; exit `$LASTEXITCODE"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -Command `"$command`"" -WorkingDirectory $core
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register nightly research backup of $data to $Destination at $At")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$TaskName'. 'gymctl doctor' shows the age of the last snapshot."
}
