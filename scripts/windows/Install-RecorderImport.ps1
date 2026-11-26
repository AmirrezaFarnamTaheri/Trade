#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Repository = 'AmirrezaFarnamTaheri/Trade',
    [string]$TaskName = 'TradingGYM Recorder Import',
    [switch]$Uninstall
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Remove recorder import schedule')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    return
}
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Invalid repository.' }
$core = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\gym-core')).Path
$python = Join-Path $core '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Install the local Python environment first.' }
$null = Get-Command gh -ErrorAction Stop
$source = Join-Path $core 'scripts\venue_recorder.py'
$hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$state = [IO.Path]::GetFullPath((Join-Path $core '..\data\live\recorder-import'))
$published = Join-Path $state ('venue-recorder-' + $hash.ToLowerInvariant() + '.py')
$database = [IO.Path]::GetFullPath((Join-Path $core '..\data\live\recorder.sqlite3'))
$arguments = '"{0}" sync --repo {1} --db "{2}"' -f $published, $Repository, $database
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $state
$trigger = New-ScheduledTaskTrigger -Daily -At '04:15'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, 'Schedule daily import of hosted recorder artifacts')) {
    # The standalone script must survive switching the review checkout to an older branch.
    New-Item -ItemType Directory -Path $state -Force | Out-Null
    if (-not (Test-Path -LiteralPath $published)) { Copy-Item -LiteralPath $source -Destination $published }
    if ((Get-FileHash -LiteralPath $published -Algorithm SHA256).Hash -cne $hash) { throw 'Published recorder hash mismatch.' }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
}
