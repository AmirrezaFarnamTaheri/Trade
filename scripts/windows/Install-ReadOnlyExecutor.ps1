#Requires -RunAsAdministrator
<#
Install a DISABLED, read-only Windows SCM bootstrap (not funded, not a live
stop-protection service). Run explicitly from an elevated PowerShell window.
No secrets, network access, or venue APIs are provisioned. T2 pipe ACL is created
by the service: SYSTEM/service full access, Administrators data-only (no pipe-create).
Do not change the service to automatic start as part of this script.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $BinaryPath,
    [Parameter(Mandatory = $true)][string] $OperatorAccount,
    [Parameter(Mandatory = $true)][ValidateRange(1, 4294967295)][uint32] $OperatorProcessId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') { throw 'This installer runs only on Windows.' }
$ServiceName = 'TradingGYMExecutor'
$CodeRoot = Join-Path ${env:ProgramFiles} 'TradingGYM'
$CodeDir = Join-Path $CodeRoot 'Executor'
$ExePath = Join-Path $CodeDir 'gym-executor.exe'
$DataRoot = Join-Path ${env:ProgramData} 'TradingGYM'
$DataDir = Join-Path $DataRoot 'Executor'

# Only an explicit elevated action may create/modify these local resources.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'An elevated administrator token is required.'
}
$inputFile = Get-Item -LiteralPath $BinaryPath -ErrorAction Stop
if ($inputFile.PSIsContainer -or $inputFile.Extension -ine '.exe' -or
    (($inputFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
    throw 'BinaryPath must be an existing regular .exe file, not a link.'
}
if ([IO.Path]::GetFullPath($inputFile.FullName) -ieq [IO.Path]::GetFullPath($ExePath)) {
    throw 'Choose a staging binary outside the protected destination directory.'
}
if (Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'") {
    throw 'Service already exists; manual review is required before any reinstall.'
}
# Reuse of pre-existing directories is forbidden until a separate secure
# migration can prove parent ownership and reject replacement/reparse races.
foreach ($path in @($CodeRoot, $DataRoot)) {
    if (Test-Path -LiteralPath $path) {
        throw "Existing install root requires manual review: $path"
    }
}

$operatorSid = ([Security.Principal.NTAccount]::new($OperatorAccount)).Translate([Security.Principal.SecurityIdentifier]).Value
$null = & (Join-Path $PSScriptRoot 'Get-OperatorLogonSid.ps1') -OperatorProcessId $OperatorProcessId -ExpectedUserSid $operatorSid
$helpers = @('gym-stopctl.exe', 'gym-hardstop.exe', 'gym-provision.exe', 'gym-account-read.exe', 'gym-ceiling.exe', 'gym-review.exe', 'gym-research-worker.exe') | ForEach-Object {
    $file = Get-Item -LiteralPath (Join-Path $inputFile.DirectoryName $_) -ErrorAction Stop
    if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Helper must be a regular staging executable.' }
    @{ File = $file; Hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash }
}
$sourceHash = (Get-FileHash -LiteralPath $inputFile.FullName -Algorithm SHA256).Hash
$target = "$ExePath / $DataDir (service remains DISABLED)"
if (-not $PSCmdlet.ShouldProcess($target, 'Install read-only Executor service identity and ACLs')) {
    return
}

function Invoke-Sc {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "sc.exe failed with code $LASTEXITCODE" }
}
function Invoke-Icacls {
    param([Parameter(Mandatory = $true)][string] $Path,
          [Parameter(Mandatory = $true)][string[]] $Arguments)
    & icacls.exe $Path @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $Path with code $LASTEXITCODE" }
}

$created = $false
try {
    $null = New-Item -ItemType Directory -Path $CodeDir -Force
    $null = New-Item -ItemType Directory -Path $DataDir -Force
    foreach ($dir in @($CodeRoot, $CodeDir, $DataRoot, $DataDir)) {
        Invoke-Icacls -Path $dir -Arguments @('/inheritance:r')
        Invoke-Icacls -Path $dir -Arguments @(
            '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'
        )
        Invoke-Icacls -Path $dir -Arguments @('/setowner', '*S-1-5-32-544')
    }
    Copy-Item -LiteralPath $inputFile.FullName -Destination $ExePath -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash -ne $sourceHash) {
        throw 'Executable hash changed during copy; refusing registration.'
    }
    Invoke-Icacls -Path $ExePath -Arguments @('/inheritance:r')
    Invoke-Icacls -Path $ExePath -Arguments @('/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F')
    Invoke-Icacls -Path $ExePath -Arguments @('/setowner', '*S-1-5-32-544')

    foreach ($helper in $helpers) {
        $destination = Join-Path $CodeDir $helper.File.Name
        Copy-Item -LiteralPath $helper.File.FullName -Destination $destination -ErrorAction Stop
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $helper.Hash) { throw 'Helper hash changed during copy.' }
        Invoke-Icacls -Path $destination -Arguments @('/inheritance:r', '/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F')
        if ($helper.File.Name -in @('gym-stopctl.exe', 'gym-hardstop.exe', 'gym-review.exe', 'gym-research-worker.exe')) {
            Invoke-Icacls -Path $destination -Arguments @('/grant:r', "*${operatorSid}:RX")
        }
        Invoke-Icacls -Path $destination -Arguments @('/setowner', '*S-1-5-32-544')
    }
    foreach ($dir in @($CodeRoot, $CodeDir)) {
        Invoke-Icacls -Path $dir -Arguments @('/grant:r', "*${operatorSid}:RX")
    }

    # CIM preserves literal image-path quotes across Windows PowerShell versions.
    $registration = Invoke-CimMethod -ClassName Win32_Service -MethodName Create -Arguments @{
        Name = $ServiceName; DisplayName = $ServiceName; PathName = ('"' + $ExePath + '"')
        ServiceType = [byte]16; ErrorControl = [byte]1; StartMode = 'Disabled'
        StartName = 'NT AUTHORITY\LocalService'
    }
    if ($registration.ReturnValue -ne 0) { throw "Service registration failed: $($registration.ReturnValue)" }
    $created = $true
    # Without this descriptor Windows may grant interactive users SERVICE_START
    # or SERVICE_STOP.  Only query rights are intentionally exposed to AU.
    $serviceScmDacl = 'D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x0002008D;;;AU)'
    Invoke-Sc -Arguments @('sdset', $ServiceName, $serviceScmDacl)
    Invoke-Sc -Arguments @('sidtype', $ServiceName, 'restricted')
    Invoke-Sc -Arguments @('description', $ServiceName,
        'DISARMED bootstrap; credential custody only; venue permissions UNVERIFIED; no funded authority')

    $serviceSid = ([Security.Principal.NTAccount]::new("NT SERVICE\$ServiceName")).Translate(
        [Security.Principal.SecurityIdentifier]).Value
    if ($serviceSid -notmatch '^S-1-5-80-([0-9]+-){4}[0-9]+$') {
        throw 'Windows did not resolve a valid isolated service SID.'
    }
    $readCode = "*${serviceSid}:(OI)(CI)RX"
    $modifyData = "*${serviceSid}:(OI)(CI)M"
    Invoke-Icacls -Path $CodeRoot -Arguments @('/grant:r', $readCode)
    Invoke-Icacls -Path $CodeDir -Arguments @('/grant:r', $readCode)
    Invoke-Icacls -Path $ExePath -Arguments @('/grant:r', "*${serviceSid}:RX")
    foreach ($helper in $helpers) {
        Invoke-Icacls -Path (Join-Path $CodeDir $helper.File.Name) -Arguments @('/grant:r', "*${serviceSid}:RX")
    }
    Invoke-Icacls -Path $DataRoot -Arguments @('/grant:r', $readCode)
    Invoke-Icacls -Path $DataDir -Arguments @('/grant:r', $modifyData)

    # OWNER RIGHTS suppresses shared LocalService implicit owner WRITE_DAC on new files.
    # No LocalService ACE: access requires the restricted, enabled service SID.
    $vaultDir = Join-Path $DataDir 'Vault'
    $null = New-Item -ItemType Directory -Path $vaultDir
    $vaultAcl = [Security.AccessControl.DirectorySecurity]::new()
    $vaultAcl.SetSecurityDescriptorSddlForm("O:BAD:P(A;OICI;RC;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;${serviceSid})")
    Set-Acl -LiteralPath $vaultDir -AclObject $vaultAcl

    # Derive the operator SID from the actual TokenLogonSid OS token class.
    $logonSid = & (Join-Path $PSScriptRoot 'Get-OperatorLogonSid.ps1') -OperatorProcessId $OperatorProcessId -ExpectedUserSid $operatorSid
    if ($logonSid -notmatch '^S-1-5-5-[0-9]+-[0-9]+$') {
        throw 'Windows did not return a valid operator logon SID.'
    }
    # Keep authorization in CodeDir (service RX) NOT DataDir (service Modify).
    $stopSidPath = Join-Path $CodeDir 'stop-logon.sid'
    [IO.File]::WriteAllText($stopSidPath, $logonSid, [Text.Encoding]::ASCII)
    Invoke-Icacls -Path $stopSidPath -Arguments @('/inheritance:r')
    Invoke-Icacls -Path $stopSidPath -Arguments @(
        '/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F', "*${serviceSid}:R"
    )
    Invoke-Icacls -Path $stopSidPath -Arguments @('/setowner', '*S-1-5-32-544')
    # The exact OS-issued operator user SID is a second mandatory principal.
    $userSid = $operatorSid
    if ($userSid -notmatch '^S-1-[0-9]+(-[0-9]+){2,12}$' -or $userSid.Length -gt 120) {
        throw 'Windows did not provide a valid operator user SID.'
    }
    $stopUserPath = Join-Path $CodeDir 'stop-user.sid'
    [IO.File]::WriteAllText($stopUserPath, $userSid, [Text.Encoding]::ASCII)
    Invoke-Icacls -Path $stopUserPath -Arguments @('/inheritance:r')
    Invoke-Icacls -Path $stopUserPath -Arguments @(
        '/grant:r', '*S-1-5-18:F', '*S-1-5-32-544:F', "*${serviceSid}:R"
    )
    Invoke-Icacls -Path $stopUserPath -Arguments @('/setowner', '*S-1-5-32-544')

    & (Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Isolation verification script failed.' }
    Write-Output "Registered DISABLED read-only service $ServiceName. No money or stop protection is active."
}
catch {
    if ($created) {
        try { Invoke-Sc -Arguments @('config', $ServiceName, 'start=', 'disabled') } catch {}
    }
    throw
}
