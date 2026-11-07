#Requires -Version 5.1
<# Runs the observation-only collector at logon for the current user and restarts it after a failure.
   No administrator rights, no service account, no secrets: `gymctl run` only reads public market data.
   Events go to <data>\<store>\events.jsonl (rotated at 50 MB, three files kept).
   Remove with -Uninstall.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$CoreDirectory,
    [string]$DataDirectory,
    [string]$TaskName = 'TradingGYM Collector',
    [string[]]$CollectorArguments = @('--no-browser', '--assets', 'all'),
    [string]$LinkFile = (Join-Path $env:LOCALAPPDATA 'TradingGYM\workspace-link.txt'),
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    return
}

if (-not $CoreDirectory) { $CoreDirectory = Join-Path $PSScriptRoot '..\..\gym-core' }
if (-not $DataDirectory) { $DataDirectory = Join-Path $PSScriptRoot '..\..\data' }
$core = (Resolve-Path -LiteralPath $CoreDirectory).Path
$python = Join-Path $core '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the gym-core environment with uv sync first.' }
$data = [IO.Path]::GetFullPath($DataDirectory)
$arguments = @('-I', '-B', '-m', 'gym.cli', '--data', "`"$data`"", 'run', '--link-file', "`"$LinkFile`"") + $CollectorArguments
$action = New-ScheduledTaskAction -Execute $python -Argument ($arguments -join ' ') -WorkingDirectory $core
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
# Restart every minute after a failure, up to 999 times; never stop a long-running collector for running too long.
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register: $python $($arguments -join ' ') in $core")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Registered and started '$TaskName'. Open the private link in $LinkFile (it changes at every start)."
}
