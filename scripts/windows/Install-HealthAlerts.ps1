#Requires -Version 5.1
<# Every 30 minutes, run the quick health check and push a Windows toast when the state changes
   (collector feed stale, low disk, backups older than 36 h, and recovery). -Webhook adds one https endpoint that
   accepts a plain-text POST, for example https://ntfy.sh/<your-private-topic> to reach a phone.
   Preview with -WhatIf; remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DataDirectory,
    [string]$CoreDirectory,
    [ValidateRange(5, 1440)][int]$EveryMinutes = 30,
    [string]$Webhook,
    [string]$TaskName = 'TradingGYM Health Alerts',
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
if ($Webhook -and $Webhook -notmatch '^https://[^\s/@''"]+(/[^\s''"]*)?$') { throw 'Webhook must be an https URL without credentials or quotes.' }
$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$data = [IO.Path]::GetFullPath($DataDirectory)
$uv = (Get-Command uv -ErrorAction Stop).Source
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$hook = if ($Webhook) { " --webhook '$Webhook'" } else { '' }
$command = "& '$uv' run --no-sync gymctl --data '$data' doctor --quick --notify --json$hook | Out-Null"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$command`"" -WorkingDirectory $core
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register health alerts for $data every $EveryMinutes min")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$TaskName'. A toast appears only when the health state changes."
}
