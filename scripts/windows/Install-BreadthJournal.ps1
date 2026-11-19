#Requires -Version 5.1
<# Once a day at 15:00 Tehran (the cheapest Wallex spread hour), refresh every USDT market's daily candles and append
   one paper decision to the breadth journal (trial breadth-trend-forward in gym-core/docs/trial-log.md).
   Paper only: nothing is sent to the venue. A missed day is not back-filled. A fill needs a fresh quote, so the
   collector must be running. Preview with -WhatIf; remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DataDirectory,
    [string]$CoreDirectory,
    [ValidatePattern('^\d{2}:\d{2}$')][string]$At = '15:00',
    [string]$TaskName = 'TradingGYM Breadth Journal',
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
$command = "& '$uv' run --no-sync gymctl --data '$data' breadth-journal --refresh | Out-Null"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$command`"" -WorkingDirectory $core
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register the daily breadth journal at $At")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$TaskName', daily at $At local time."
}
