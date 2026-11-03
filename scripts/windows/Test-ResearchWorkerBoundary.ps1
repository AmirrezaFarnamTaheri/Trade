#Requires -Version 5.1
<# Operator-only live negative probes. No profile/ACL/service changes, no pipe
   messages, no writes, no credentials read. Uses the actual R0 child token.
   Missing targets are NOT_VERIFIED, never evidence of isolation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Launcher,
    [Parameter(Mandatory=$true)][string]$InstallDirectory
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($InstallDirectory -notmatch '^[A-Za-z]:\\' -or $InstallDirectory -match '["\r\n]') { throw 'Explicit installation path required' }
$targets = Get-Content -LiteralPath (Join-Path $InstallDirectory 'boundary.json') -Raw | ConvertFrom-Json
# Host-side existence observations prevent ERROR_ACCESS_DENIED on an absent
# target/ancestor being mistaken for proof that the intended resource was tested.
try {
    $pipes = @([IO.Directory]::GetFiles('\\.\pipe\'))
    foreach ($name in @('stop_pipe', 't2_pipe')) {
        if ($targets.$name -notin $pipes) { throw "missing pipe: $name" }
    }
    foreach ($name in @('vault', 'core_journal')) {
        if (-not (Test-Path -LiteralPath $targets.$name -PathType Leaf)) { throw "missing file: $name" }
    }
    $service = Get-Service -Name $targets.service -ErrorAction Stop
    if ($service.Name -ne $targets.service) { throw 'SCM target mismatch' }
} catch {
    Write-Output "NOT_VERIFIED: target existence unavailable: $_"
    exit 3
}
$info = [Diagnostics.ProcessStartInfo]::new()
$info.FileName = (Resolve-Path -LiteralPath $Launcher).Path
$info.Arguments = '"' + $InstallDirectory.TrimEnd('\') + '" --boundary-probe'
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardInput = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$process = [Diagnostics.Process]::new()
$process.StartInfo = $info
try {
    if (-not $process.Start()) { throw 'Launcher did not start' }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(310000)) {
        $process.Kill() # Closing the launcher job kills its child; no other process is targeted.
        throw 'NOT_VERIFIED: launcher deadline exceeded'
    }
    $output = $stdout.GetAwaiter().GetResult()
    $errors = $stderr.GetAwaiter().GetResult()
    $records = @($output -split '\r?\n' | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
    $reports = @($records | Where-Object { $_.PSObject.Properties['probe'] })
    $catalogs = @($records | Where-Object { $_.PSObject.Properties['result'] })
    if ($reports.Count -ne 1 -or $catalogs.Count -ne 1) { throw "NOT_VERIFIED: actual child probe and R0 response required. $errors" }
    $report = $reports[0]
    $sid = (Get-Content -LiteralPath (Join-Path $InstallDirectory 'binding.txt') -Raw).Trim()
    if ($report.probe -ne 'actual_R0_child' -or $report.pid -le 0 -or $errors -notmatch ([regex]::Escape("R0 child PID=$($report.pid) AppContainer=$sid capabilities=0 (verified suspended)"))) { throw 'NOT_VERIFIED: native token/Python child PID evidence mismatch' }
    $names = @($catalogs[0].result.tools | ForEach-Object { $_.name } | Sort-Object)
    if (($names -join ',') -ne 'market_coverage,research_state,strategy_catalog') { throw 'FAIL: actual child R0 tool set changed' }
    $expected = @('core_journal', 'service', 'stop_pipe', 't2_pipe', 'vault')
    if ((@($report.results.PSObject.Properties.Name | Sort-Object) -join ',') -ne ($expected -join ',')) { throw 'NOT_VERIFIED: incomplete probe report' }
    $report | ConvertTo-Json -Depth 5
    if ($process.ExitCode -ne 0 -or @($report.results.PSObject.Properties | Where-Object { $_.Value -ne 'DENIED' }).Count -ne 0) { throw 'FAIL/NOT_VERIFIED: one or more child-token probes were not denied' }
    Write-Output 'Observed DENIED for existing targets from actual R0 child; not a security certification. Re-run after policy or deployment changes.'
} finally { $process.Dispose() }
