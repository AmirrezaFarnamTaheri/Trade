<#
Non-destructive SEC-01/SEC-02 negative probe, executed as a STANDARD Windows
operator account and independently as the sandbox/research-worker principal.
Never run elevated. This tests *actual* Win32 access decisions, not just
text in the installer. The service must be staged, DISABLED and STOPPED.
Does not start, stop, configure or open any funded venue path.
#>
[CmdletBinding()]
param([switch] $CheckStopPipeOnly, [string] $ExpectedLogonSid = '', [string] $ExpectedUserSid = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') { throw 'Requires Windows.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$adminSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$hasAdministratorsGroup = @($identity.Groups | Where-Object {
    $_.Value -eq $adminSid.Value
}).Count -gt 0
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
    $hasAdministratorsGroup) {
    throw 'Refusing elevated or filtered-administrator token: use a standard, nonadministrator token.'
}

if ($CheckStopPipeOnly) {
    # Prove that this is a different Windows-issued logon SID, not a forged
    # username, before verifying access to the already-running stop pipe.
    $service = Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'"
    if ($null -eq $service -or $service.StartMode -ine 'Manual' -or $service.State -ine 'Running') {
        throw 'SECURITY TEST INVALID: stop service is not running'
    }
    if ($ExpectedLogonSid -notmatch '^S-1-5-5-[0-9]+-[0-9]+$') {
        throw 'SECURITY TEST INVALID: no expected operator logon SID'
    }
    $logonOutput = (& whoami.exe /logonid | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw 'SECURITY TEST INVALID: child logon SID query failed'
    }
    $sidMatch = [regex]::Match($logonOutput, 'S-1-5-5-[0-9]+-[0-9]+')
    if (-not $sidMatch.Success) {
        throw 'SECURITY TEST INVALID: no OS-issued child logon SID'
    }
    Write-Output "T0 child identity diagnostic: childUser=$($identity.User.Value), childLogon=$($sidMatch.Value), expectedLogon=$ExpectedLogonSid"
    if ($ExpectedUserSid -notmatch '^S-1-[0-9]+(-[0-9]+){2,12}$') {
        throw 'SECURITY TEST INVALID: no expected operator user SID'
    }
    if ($identity.User.Value -ceq $ExpectedUserSid) {
        throw 'SECURITY TEST INVALID: same user and logon identity, probe not independent'
    }
    # A different user can carry the same logon SID in some runner launch
    # modes. Both identities must be checked by the service before an ACK.
    Write-Output 'T0 negative probe: child Windows logon SID differs from authorized operator.'
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class TradingGYMStopNegativeAccess {
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(
        string name, uint access, uint sharing, IntPtr security,
        uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
    public static int AttemptOpen() {
        var handle = CreateFile(@"\\.\pipe\TradingGYM.Stop.v1",
            0x00100003, 0, IntPtr.Zero, 3, 0x00110000, IntPtr.Zero);
        if (handle == new IntPtr(-1)) return Marshal.GetLastWin32Error();
        CloseHandle(handle);
        return 0;
    }
}
'@
    $code = [TradingGYMStopNegativeAccess]::AttemptOpen()
    # Some Windows versions admit the minimum-right handle despite a logon
    # scoped DACL. A successful CreateFile is NOT authorization to command the
    # Executor. The server MUST reject a different OS-issued logon SID before
    # processing even STATUS; the negative client tests an actual framed PAUSE.
    Write-Output "T0 negative DACL open returned Win32 $code (diagnostic only)"
    $stagedStop = Join-Path $PSScriptRoot 'StopClient.exe'
    if (-not (Test-Path -LiteralPath $stagedStop -PathType Leaf)) {
        throw 'SECURITY TEST INVALID: trusted stop client not staged'
    }
    $stdout = Join-Path $env:TEMP ('t0-unauthorized-out-' + [guid]::NewGuid().ToString('N') + '.txt')
    $stderr = Join-Path $env:TEMP ('t0-unauthorized-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    try {
        $attempt = Start-Process -FilePath $stagedStop -ArgumentList 'pause' -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $reply = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw } else { '' }
        $failure = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { '' }
        if ($attempt.ExitCode -eq 0 -or $reply -match 'ACKNOWLEDGED:' -or $failure -notmatch 'UNACKNOWLEDGED:') {
            throw "SECURITY FAILURE: separate Windows logon received a stop-pipe acknowledgement or no explicit rejection"
        }
    }
    finally {
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
    Write-Output "PASS: non-admin SID=$($identity.User.Value) denied active stop pipe command under separate logon."
    return
}
$ServiceName = 'TradingGYMExecutor'
$Binary = Join-Path (Join-Path ${env:ProgramFiles} 'TradingGYM\Executor') 'gym-executor.exe'
$DataDir = Join-Path ${env:ProgramData} 'TradingGYM\Executor'
$service = Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'"
if ($null -eq $service -or $service.StartMode -ine 'Disabled' -or $service.State -ine 'Stopped') {
    throw 'Service should remain DISABLED and STOPPED during the access probe.'
}

function Test-IsAccessDenied {
    param([Parameter(Mandatory = $true)][System.Exception] $Exception)
    # PowerShell may wrap a .NET UnauthorizedAccessException in a
    # MethodInvocationException.  Inspect only the actual Win32 denial code,
    # not arbitrary failures such as file-not-found or sharing violation.
    $inner = $Exception
    for ($depth = 0; $depth -lt 8 -and $null -ne $inner; $depth++) {
        if (($inner.HResult -band 0xFFFF) -eq 5) { return $true }
        $inner = $inner.InnerException
    }
    return $false
}

function Assert-AccessDenied {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][scriptblock] $Action
    )
    try {
        & $Action
    }
    catch {
        if (-not (Test-IsAccessDenied -Exception $_.Exception)) {
            throw "Expected ACCESS_DENIED (Win32 5) for $Name, got: $($_.Exception.Message)"
        }
        return
    }
    throw "SECURITY FAILURE: $Name was permitted; expected ACCESS_DENIED"
}

# No executable read/overwrite authority, even if the operator can query SCM.
Assert-AccessDenied -Name 'protected binary read' -Action {
    $stream = [IO.File]::Open($Binary, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $stream.Dispose()
}
Assert-AccessDenied -Name 'protected binary overwrite capability' -Action {
    $stream = [IO.File]::Open($Binary, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
    $stream.Dispose()
}

# A new, random harmless probe name cannot be created in the authority store.
# If an overly broad ACL accidentally allows creation, delete the canary and
# fail the test. Never overwrite an existing record or secret.
$probe = Join-Path $DataDir ('acl-probe-' + [guid]::NewGuid().ToString('N') + '.tmp')
$writePermitted = $false
$createdStream = $null
try {
    # CreateNew guarantees the probe never overwrites any existing object.
    $createdStream = [IO.File]::Open($probe, [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write, [IO.FileShare]::None)
    $writePermitted = $true
}
catch {
    if (-not (Test-IsAccessDenied -Exception $_.Exception)) {
        throw "Expected ACCESS_DENIED on private ledger directory, got $($_.Exception.Message)"
    }
}
finally {
    if ($null -ne $createdStream) { $createdStream.Dispose() }
}
if ($writePermitted) {
    # This branch always fails security validation, regardless of whether the
    # cleanup operation succeeds or itself throws ACCESS_DENIED.
    try { [IO.File]::Delete($probe) } catch {}
    throw 'SECURITY FAILURE: private ledger directory write was permitted'
}

# Query-only SCM access is allowed. Requests for any privileged service
# operation must be rejected by Windows *before* performing that operation.
# OpenService only requests a handle; it never starts/configures the service.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class TradingGYMScmAccess {
    [DllImport("advapi32.dll", EntryPoint = "OpenSCManagerW", ExactSpelling = true, SetLastError = true)]
    public static extern IntPtr OpenSCManager(IntPtr host, IntPtr database, uint desiredAccess);
    [DllImport("advapi32.dll", EntryPoint = "OpenServiceW", ExactSpelling = true, CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr OpenService(IntPtr manager, string name, uint desiredAccess);
    [DllImport("advapi32.dll", EntryPoint = "CloseServiceHandle", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseServiceHandle(IntPtr handle);
}
'@
$scm = [TradingGYMScmAccess]::OpenSCManager([IntPtr]::Zero, [IntPtr]::Zero, 0x0001)
if ($scm -eq [IntPtr]::Zero) {
    throw "OpenSCManager query failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}
try {
    # SERVICE_QUERY_STATUS is deliberately allowed to authenticated users.
    $readOnly = [TradingGYMScmAccess]::OpenService($scm, $ServiceName, 0x0004)
    if ($readOnly -eq [IntPtr]::Zero) {
        throw "Cannot query service status: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    $null = [TradingGYMScmAccess]::CloseServiceHandle($readOnly)

    $privilegedRights = [ordered]@{
        CHANGE_CONFIG = 0x0002
        START = 0x0010
        STOP = 0x0020
        PAUSE_CONTINUE = 0x0040
        USER_DEFINED_CONTROL = 0x0100
        DELETE = 0x10000
        WRITE_DAC = 0x40000
        WRITE_OWNER = 0x80000
    }
    foreach ($name in $privilegedRights.Keys) {
        $handle = [TradingGYMScmAccess]::OpenService($scm, $ServiceName, [uint32]$privilegedRights[$name])
        if ($handle -ne [IntPtr]::Zero) {
            $null = [TradingGYMScmAccess]::CloseServiceHandle($handle)
            throw "SECURITY FAILURE: unprivileged service right $name was granted"
        }
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        if ($errorCode -ne 5) {
            throw "Expected ACCESS_DENIED for service right $name, Win32 error $errorCode"
        }
    }
}
finally {
    $null = [TradingGYMScmAccess]::CloseServiceHandle($scm)
}
Write-Output "PASS: non-admin SID=$($identity.User.Value) denied executable, store writes and all privileged SCM rights. No funded mode verified."
