#Requires -RunAsAdministrator
# Re-run after each selected operator logon, while the Executor is stopped.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)][string] $OperatorAccount,
    [Parameter(Mandatory = $true)][ValidateRange(1, 4294967295)][uint32] $OperatorProcessId
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$service = Get-CimInstance Win32_Service -Filter "Name = 'TradingGYMExecutor'"
if ($null -eq $service -or $service.State -ne 'Stopped' -or $service.StartMode -ne 'Disabled') {
    throw 'Binding requires the existing Executor stopped and DISABLED.'
}
$userSid = ([Security.Principal.NTAccount]::new($OperatorAccount)).Translate([Security.Principal.SecurityIdentifier]).Value
$logonSid = & (Join-Path $PSScriptRoot 'Get-OperatorLogonSid.ps1') -OperatorProcessId $OperatorProcessId -ExpectedUserSid $userSid
$serviceSid = ([Security.Principal.NTAccount]::new('NT SERVICE\TradingGYMExecutor')).Translate([Security.Principal.SecurityIdentifier]).Value
$root = Join-Path $env:ProgramFiles 'TradingGYM'
$code = Join-Path $root 'Executor'
$trusted = @('S-1-5-18', 'S-1-5-32-544',
    ([Security.Principal.NTAccount]::new('NT SERVICE\TrustedInstaller')).Translate([Security.Principal.SecurityIdentifier]).Value)
foreach ($path in @($env:ProgramFiles, $root, $code)) {
    $item = Get-Item -LiteralPath $path
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Untrusted binding path.' }
    $acl = Get-Acl -LiteralPath $path
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted -and $path -ne $env:ProgramFiles) { throw 'Untrusted binding owner.' }
    foreach ($ace in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($ace.AccessControlType -eq 'Allow' -and $ace.IdentityReference.Value -notin $trusted -and
            (([int64]$ace.FileSystemRights -band 0x000D0156) -ne 0)) { throw 'Binding directory is writable by another principal.' }
    }
}
if (-not $PSCmdlet.ShouldProcess($OperatorAccount, 'Bind STOP to actual selected user token and current logon')) { return }
foreach ($path in @($root, $code, (Join-Path $code 'gym-stopctl.exe'), (Join-Path $code 'gym-hardstop.exe'))) {
    $item = Get-Item -LiteralPath $path
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing linked helper path.' }
    & icacls.exe $path /grant:r "*${userSid}:RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Operator helper access grant failed.' }
}
# Invalidate the old binding first: interruption must fail closed, never mix logons.
$logonPath = Join-Path $code 'stop-logon.sid'
Remove-Item -LiteralPath $logonPath -Force -ErrorAction Stop
foreach ($entry in @(@('stop-user.sid', $userSid), @('stop-logon.sid', $logonSid))) {
    $path = Join-Path $code $entry[0]
    if (Test-Path -LiteralPath $path) {
        $file = Get-Item -LiteralPath $path
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing linked binding file.' }
        Remove-Item -LiteralPath $path -Force
    }
    [IO.File]::WriteAllText($path, $entry[1], [Text.Encoding]::ASCII)
    & icacls.exe $path /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "*${serviceSid}:R" | Out-Null
    if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $logonPath -Force -ErrorAction SilentlyContinue; throw 'Binding ACL failed.' }
    & icacls.exe $path /setowner '*S-1-5-32-544' | Out-Null
    if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $logonPath -Force -ErrorAction SilentlyContinue; throw 'Binding owner failed.' }
}
Write-Output 'STOP bound to selected OS user/logon. Service remains DISABLED; no protection claimed.'
