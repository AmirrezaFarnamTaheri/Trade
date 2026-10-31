#Requires -RunAsAdministrator
<#
Ephemeral, no-secret Windows integration test for the disabled B1 SCM bootstrap.
Refuses developer/self-hosted machines. Never connects to a trading venue or
passes credentials to the Executor. Two random local non-admin accounts are
created only to exercise the OS's effective access checks, then removed.

On this disposable hosted runner ONLY, the no-op read-only service is briefly
changed to manual start to prove its OS-token identity gate, then stopped and
restored to DISABLED before the hostile-account probes and cleanup.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $BinaryPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or
    $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Refusing Windows integration outside disposable GitHub-hosted CI.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'An elevated CI administrator token is required.'
}

$ServiceName = 'TradingGYMExecutor'
$CodeRoot = Join-Path $env:ProgramFiles 'TradingGYM'
$CodeDir = Join-Path $CodeRoot 'Executor'
$DataRoot = Join-Path $env:ProgramData 'TradingGYM'
$ExePath = Join-Path $CodeRoot 'Executor\gym-executor.exe'
$Installer = Join-Path $PSScriptRoot 'Install-ReadOnlyExecutor.ps1'
$Audit = Join-Path $PSScriptRoot 'Test-ReadOnlyExecutor.ps1'
$Denial = Join-Path $PSScriptRoot 'Test-UnprivilegedExecutorAccess.ps1'
$ReportRoot = Join-Path $env:RUNNER_TEMP ('tradinggym-b1-smoke-' + [guid]::NewGuid().ToString('N'))
$UsersCreated = [System.Collections.Generic.List[string]]::new()
$ErrorsDuringCleanup = [System.Collections.Generic.List[string]]::new()
$RunFailure = $null
$OwnServiceInstall = $false
$ReportCreated = $false

function Invoke-ScChecked {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "sc.exe operation failed (code $LASTEXITCODE)" }
}
function Assert-ServiceState {
    param([string] $StartMode, [string] $State)
    $service = Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'"
    if ($null -eq $service -or $service.StartMode -ne $StartMode -or $service.State -ne $State) {
        throw "Unexpected service state; expected $StartMode / $State"
    }
}
function Invoke-UnprivilegedProbe {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][System.Security.SecureString] $Password,
        [Parameter(Mandatory = $true)][string] $Role
    )
    $User = Get-LocalUser -Name $Name -ErrorAction Stop
    $sid = $User.SID.Value
    $dir = Join-Path $ReportRoot $Role
    $scratch = Join-Path $ReportRoot ($Role + '-scratch')
    $null = New-Item -ItemType Directory -Path $dir -Force
    $null = New-Item -ItemType Directory -Path $scratch -Force
    # The user may read the test, but must not rewrite the test code that
    # determines whether an access-denied response is genuine.
    & icacls.exe $dir '/inheritance:r' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot protect probe source directory' }
    & icacls.exe $dir '/grant:r' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${sid}:(OI)(CI)RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot set read-only probe source ACL' }
    & icacls.exe $scratch '/inheritance:r' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot protect isolated probe scratch directory' }
    & icacls.exe $scratch '/grant:r' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${sid}:(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot grant only intended user access to scratch' }
    $ScriptCopy = Join-Path $dir 'UnprivilegedProbe.ps1'
    Copy-Item -LiteralPath $Denial -Destination $ScriptCopy -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $ScriptCopy -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $Denial -Algorithm SHA256).Hash) {
        throw 'Unprivileged probe was modified during staging'
    }
    $stdout = Join-Path $scratch 'stdout.txt'
    $stderr = Join-Path $scratch 'stderr.txt'
    $credential = [PSCredential]::new("$env:COMPUTERNAME\$Name", $Password)
    $PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $childArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $ScriptCopy + '"'
    # The parent GitHub runner has TEMP under runneradmin's private profile.
    # Add-Type compiles a temporary C# helper in the child process: using the
    # inherited TEMP makes the real standard user fail before testing SCM.
    if (-not (Get-Command Start-Process).Parameters.ContainsKey('Environment')) {
        throw 'This test requires PowerShell 7.4+ Start-Process -Environment.'
    }
    $childEnvironment = @{ 'TEMP' = $scratch; 'TMP' = $scratch }
    $process = Start-Process -FilePath $PowerShell -ArgumentList $childArguments -Credential $credential -LoadUserProfile -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Environment $childEnvironment
    if (-not $process.WaitForExit(120000)) {
        try { $process.Kill() } catch {}
        throw "Timed out waiting for $Role OS-access probe"
    }
    $process.Refresh()
    $output = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw } else { '' }
    $errorText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { '' }
    if ($process.ExitCode -ne 0 -or $output -notmatch 'PASS: non-admin SID=.*denied executable') {
        throw "ACCESS_DENIED probe failed for $Role (exit $($process.ExitCode)); output: $output $errorText"
    }
    Write-Output "PASS: $Role (distinct local non-admin SID $sid) denied file/data/SCM privileged access."
}

try {
    if ((Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'") -or
        (Test-Path -LiteralPath $CodeRoot) -or (Test-Path -LiteralPath $DataRoot)) {
        throw 'Refusing to touch a pre-existing installation on the hosted runner.'
    }
    $OwnServiceInstall = $true
    $binary = (Resolve-Path -LiteralPath $BinaryPath -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
        throw 'A built read-only service binary is required.'
    }
    if (Test-Path -LiteralPath $ReportRoot) { throw 'Report folder already exists.' }
    $null = New-Item -ItemType Directory -Path $ReportRoot -ErrorAction Stop
    $ReportCreated = $true

    & $Installer -BinaryPath $binary -WhatIf
    if ((Get-CimInstance -ClassName Win32_Service -Filter "Name = 'TradingGYMExecutor'") -or
        (Test-Path -LiteralPath $CodeRoot) -or (Test-Path -LiteralPath $DataRoot)) {
        throw '-WhatIf created an installation unexpectedly.'
    }
    & $Installer -BinaryPath $binary -Confirm:$false
    Assert-ServiceState -StartMode 'Disabled' -State 'Stopped'
    & $Audit
    if ((Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash) {
        throw 'Installed executable hash does not match reviewed build.'
    }

    # A real SCM launch is needed to exercise the OS-issued restricted service
    # token gate. This read-only service has no pipe, keys, network or order path.
    Invoke-ScChecked -Arguments @('config', $ServiceName, 'start=', 'demand')
    Start-Service -Name $ServiceName -ErrorAction Stop
    Assert-ServiceState -StartMode 'Manual' -State 'Running'
    Write-Output 'PASS: OS launched read-only service under verified restricted token.'
    # Report *only boolean* token characteristics, never reusable SIDs or
    # secrets. A grant to the installer logon SID cannot authorize a client
    # from a different logon, or a token subject to a deny NETWORK ACE.
    $expectedSid = (Get-Content -LiteralPath (Join-Path $CodeDir 'stop-logon.sid') -Raw).Trim()
    $actualSid = (& (Join-Path $PSScriptRoot 'Get-OperatorLogonSid.ps1')).Trim()
    $identityGroups = @([Security.Principal.WindowsIdentity]::GetCurrent().Groups |
        ForEach-Object { $_.Value })
    $hasNetworkSid = ($identityGroups -contains 'S-1-5-2')
    Write-Output "T0 ACL preflight: logon-match=$($expectedSid -ceq $actualSid) network-token-group=$hasNetworkSid"
    if ($expectedSid -cne $actualSid) {
        throw 'The stop-pipe client token does not match privileged installation logon.'
    }
    $StopClient = Join-Path (Split-Path -Parent $binary) 'gym-stopctl.exe'
    if (-not (Test-Path -LiteralPath $StopClient -PathType Leaf)) {
        throw 'Compiled gym-stopctl.exe is required for T0 verification.'
    }
    foreach ($command in @('pause', 'exit-only', 'halt')) {
        $reply = & $StopClient $command 2>&1
        if ($LASTEXITCODE -ne 0 -or ($reply -join ' ') -notmatch '^ACKNOWLEDGED:') {
            throw "Stop-only pipe did not acknowledge ${command}: $($reply -join ' ')"
        }
        Write-Output "PASS: stop-only pipe $command ACKNOWLEDGED"
    }
    Stop-Service -Name $ServiceName -ErrorAction Stop
    Invoke-ScChecked -Arguments @('config', $ServiceName, 'start=', 'disabled')
    Assert-ServiceState -StartMode 'Disabled' -State 'Stopped'
    & $Audit

    # Separate random local accounts. No passwords are persisted, printed,
    # stored in repo variables, or passed to the Executor service process.
    foreach ($role in @('operator', 'worker')) {
        $name = if ($role -eq 'operator') { 'tgop' } else { 'tgwk' }
        $name += [guid]::NewGuid().ToString('N').Substring(0, 8)
        $random = [byte[]]::new(32)
        [Security.Cryptography.RandomNumberGenerator]::Fill($random)
        $password = ConvertTo-SecureString ([Convert]::ToBase64String($random) + 'Aa9!') -AsPlainText -Force
        $null = New-LocalUser -Name $name -Password $password -AccountExpires (Get-Date).AddHours(1) -Description "Disposable TradingGYM $role probe"
        $UsersCreated.Add($name)
        Invoke-UnprivilegedProbe -Name $name -Password $password -Role $role
    }
    Assert-ServiceState -StartMode 'Disabled' -State 'Stopped'
    Write-Output 'PASS: disposable Windows VM read-only SCM, ACL and two-principal negative probes.'
}
catch {
    $RunFailure = $_
}
finally {
    # A crash or failed assertion must never leave even the no-op service
    # enabled or running on the test VM.
    if ($OwnServiceInstall) {
        try {
            $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
            if ($null -ne $service) {
                if ($service.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force -ErrorAction Stop }
                Invoke-ScChecked -Arguments @('config', $ServiceName, 'start=', 'disabled')
                Invoke-ScChecked -Arguments @('delete', $ServiceName)
            }
        }
        catch { $ErrorsDuringCleanup.Add("SCM cleanup: $($_.Exception.Message)") }
    }
    foreach ($name in $UsersCreated) {
        try { Remove-LocalUser -Name $name -ErrorAction Stop }
        catch { $ErrorsDuringCleanup.Add("User cleanup: $($_.Exception.Message)") }
    }
    $cleanupDirs = [System.Collections.Generic.List[string]]::new()
    if ($OwnServiceInstall) {
        $cleanupDirs.Add($CodeRoot)
        $cleanupDirs.Add($DataRoot)
    }
    if ($ReportCreated) { $cleanupDirs.Add($ReportRoot) }
    foreach ($path in $cleanupDirs) {
        if (Test-Path -LiteralPath $path) {
            try { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop }
            catch { $ErrorsDuringCleanup.Add("Directory cleanup: $($_.Exception.Message)") }
        }
    }
}
if ($null -ne $RunFailure) { throw $RunFailure }
if ($ErrorsDuringCleanup.Count -gt 0) {
    throw "Failed to clean disposable test resources: $($ErrorsDuringCleanup -join '; ')"
}
