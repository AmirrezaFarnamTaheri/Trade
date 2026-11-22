#Requires -Version 5.1
<# Once a day, fetch the latest daily candles and append one paper decision per market to the allocation journal
   (trial btc-daily-trend in gym-core/docs/trial-log.md: hold the market only while its daily close is above the 50-day average).
   Paper only: nothing is sent to the venue. A missed day is not back-filled; the next run decides on the latest
   completed candle. A fill needs a fresh quote, so the collector must be running.
   Preview with -WhatIf; remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DataDirectory,
    [string]$CoreDirectory,
    [ValidatePattern('^[A-Z0-9]{3,32}$')][string[]]$Symbols = @('BTCUSDT'),
    [ValidatePattern('^\d{2}:\d{2}$')][string]$At = '03:45',
    [string]$TaskName = 'TradingGYM Allocation Journal',
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
$markets = $Symbols -join ','
# The btc-daily-trend rule is all-in or all-out: a volatility target of 5 never binds and the band is off.
$runner = Join-Path $PSScriptRoot 'Invoke-AllocationJournal.ps1'
$command = "& '$($runner.Replace("'", "''"))' -DataDirectory '$($data.Replace("'", "''"))' -UvPath '$($uv.Replace("'", "''"))' -Symbols $markets; exit `$LASTEXITCODE"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$command`"" -WorkingDirectory $core
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register the daily allocation journal for $markets at $At")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered '$TaskName' for $markets, daily at $At local time."
}
