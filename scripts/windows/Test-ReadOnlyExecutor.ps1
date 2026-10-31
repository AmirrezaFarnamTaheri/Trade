<#
Fail-closed, nonmutating security audit of a *staged, disabled* service.
This is a host-side ACL/preflight, not proof of runtime Windows token isolation,
client impersonation resistance, pipe DACL or 1-second stop responsiveness.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Requires a Windows host.' }

$ServiceName = 'TradingGYMExecutor'
$CodeRoot = Join-Path ${env:ProgramFiles} 'TradingGYM'
$CodeDir = Join-Path $CodeRoot 'Executor'
$Binary = Join-Path $CodeDir 'gym-executor.exe'
$DataRoot = Join-Path ${env:ProgramData} 'TradingGYM'
$DataDir = Join-Path $DataRoot 'Executor'
$service = Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'"
if ($null -eq $service) { throw 'Missing SCM service registration.' }
if ($service.StartName -ine 'NT AUTHORITY\LocalService') {
    throw 'Service account is not restricted LocalService.'
}
if ($service.StartMode -ine 'Disabled') { throw 'Service must remain DISABLED.' }
if ($service.State -ine 'Stopped') { throw 'Service must remain STOPPED.' }
if ($service.PathName.Trim() -ine ('"' + $Binary + '"')) { throw 'Unexpected service executable path.' }
$sid = ([Security.Principal.NTAccount]::new('NT SERVICE\TradingGYMExecutor')).Translate(
    [Security.Principal.SecurityIdentifier]).Value
if ($sid -notmatch '^S-1-5-80-([0-9]+-){4}[0-9]+$') { throw 'Unexpected service SID.' }

# Check actual sidtype instead of trusting the prior setter's exit code.
# This localized sc.exe format may need replacement with QueryServiceConfig2W
# before multilingual Windows support is declared.
$sidtypeText = (& sc.exe qsidtype $ServiceName | Out-String)
if ($LASTEXITCODE -ne 0 -or $sidtypeText -notmatch '(?i)RESTRICTED') {
    throw 'Cannot confirm restricted service SID type.'
}

$trusted = @('S-1-5-18', 'S-1-5-32-544', $sid)
$forbidden = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-4', 'S-1-5-19')
$writeBits = [Security.AccessControl.FileSystemRights]::WriteData -bor
    [Security.AccessControl.FileSystemRights]::AppendData -bor
    [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
    [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
    [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership

foreach ($path in @($CodeRoot, $CodeDir, $Binary, $DataRoot, $DataDir)) {
    $item = Get-Item -LiteralPath $path -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Reparse point in protected path: $path"
    }
    $acl = Get-Acl -LiteralPath $path
    if (-not $acl.AreAccessRulesProtected) { throw "ACL inheritance enabled: $path" }
    $rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    $seenService = $false
    foreach ($rule in $rules) {
        $ruleSid = $rule.IdentityReference.Value
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow) {
            if ($ruleSid -in $forbidden -or $ruleSid -notin $trusted) {
                throw "Broad or unknown access rule on $path: $ruleSid"
            }
            if ($ruleSid -eq $sid) {
                $seenService = $true
                if ($path -ne $DataDir -and (($rule.FileSystemRights -band $writeBits) -ne 0)) {
                    throw "Service could overwrite code or parent directory: $path"
                }
                if ($path -eq $DataDir -and
                    (($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::WriteData) -eq 0)) {
                    throw 'Service lacks required access to isolated data directory.'
                }
            }
        }
    }
    if (-not $seenService) {
        throw "Missing service-SID allow rule: $path"
    }
}
if (-not (Test-Path -LiteralPath $Binary -PathType Leaf)) { throw 'Missing binary.' }
Write-Output "PASS: $ServiceName is disabled/stopped with isolated code/data ACLs. Runtime and funded gates are NOT certified."
