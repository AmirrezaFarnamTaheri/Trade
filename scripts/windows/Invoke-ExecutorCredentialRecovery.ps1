#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string] $SecretFile)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Requires Windows.' }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Requires an elevated administrator token.' }
# The normal preflight verifies SCM controls and protected code paths before any mutation.
& (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
$serviceName = 'TradingGYMExecutor'
$helper = Join-Path ${env:ProgramFiles} 'TradingGYM\Executor\gym-provision.exe'
if (-not $PSCmdlet.ShouldProcess($serviceName, 'Start recovery-only custody, replace credential, restart NORMAL DISARMED, restore DISABLED startup')) { return }
function Invoke-ScChecked {
    param([string[]] $Arguments)
    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'SCM recovery operation failed.' }
}
function Wait-State {
    param([string] $State)
    $service = Get-Service -Name $serviceName
    $service.WaitForStatus([ServiceProcess.ServiceControllerStatus]::$State, [TimeSpan]::FromSeconds(15))
}
$success = $false
try {
    Invoke-ScChecked -Arguments @('config', $serviceName, 'start=', 'demand')
    # StartService arguments are ephemeral and SCM-authorized, not persisted in ImagePath or sent over IPC.
    Invoke-ScChecked -Arguments @('start', $serviceName, '--credential-recovery')
    Wait-State 'Running'
    & $helper --secret-file $SecretFile
    if ($LASTEXITCODE -ne 0) { throw 'Recovery not acknowledged; outcome may be committed. Manual review required.' }
    # Recovery exits after the durable metadata ACK; it never transitions into account-read mode.
    Wait-State 'Stopped'
    Start-Service -Name $serviceName
    Wait-State 'Running'
    $success = $true
}
finally {
    try {
        if (-not $success) {
            $service = Get-Service -Name $serviceName
            if ($service.Status -ne 'Stopped') { Stop-Service -Name $serviceName -ErrorAction Stop; Wait-State 'Stopped' }
        }
    }
    finally { Invoke-ScChecked -Arguments @('config', $serviceName, 'start=', 'disabled') }
}
Write-Output 'COMMITTED: normal DISARMED service restarted; startup DISABLED. Permission UNVERIFIED; SEC03 unfulfilled. No account API was queried.'
