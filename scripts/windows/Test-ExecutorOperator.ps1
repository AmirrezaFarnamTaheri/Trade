#Requires -Version 5.1
<# Actual ordinary-operator probes. No private account reads or exchange orders.
   Uses the protected, current-runtime manifest and a zero-budget synthetic SELL
   review. Synthetic ticket fields do not attest holdings, instruments or fees.
#>
[CmdletBinding()]
param([string]$ReportPath,[switch]$SelfTest)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Review($Value) {
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=Join-Path $code 'gym-review.exe'
    $start.UseShellExecute=$false; $start.CreateNoWindow=$true
    $start.RedirectStandardInput=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    $process=[Diagnostics.Process]::new(); $process.StartInfo=$start
    try {
        if (-not $process.Start()) { throw 'Helper did not start.' }
        $stdout=$process.StandardOutput.ReadToEndAsync(); $stderr=$process.StandardError.ReadToEndAsync()
        $process.StandardInput.BaseStream.Write($Value,0,$Value.Length); $process.StandardInput.Close()
        if (-not $process.WaitForExit(7000)) { $process.Kill(); $process.WaitForExit(); throw 'Unacknowledged review deadline; inspect before retry.' }
        $output=$stdout.GetAwaiter().GetResult(); $null=$stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or $output.Length -gt 2048) { throw 'Review helper unacknowledged; operation may have committed.' }
        $body=$output|ConvertFrom-Json
        if ($body.source -cne 'EXECUTOR_SERVICE_REVIEW' -or $body.funded_authority -ne $false -or $body.order_submitted -ne $false -or $body.raw_reply_hex -cnotmatch '^[0-9a-f]{864}$') { throw 'Invalid native review envelope.' }
        return $body.raw_reply_hex
    } finally { $process.Dispose() }
}
function Put-Number([byte[]]$Frame,[int]$Offset,[uint64]$Value,[int]$Length=8) {
    for ($index=$Length-1;$index -ge 0;$index--) { $Frame[$Offset+$index]=[byte]($Value -band 255); $Value=$Value -shr 8 }
}
function Get-Number([byte[]]$Frame,[int]$Offset) {
    [uint64]$value=0
    for ($index=0;$index -lt 8;$index++) { $value=($value -shl 8) -bor [uint64]$Frame[$Offset+$index] }
    return $value
}
function Request([int]$Action,[string]$ClientId='',[uint64]$Sequence=0,[byte[]]$Ticket=$null) {
    $frame=[byte[]]::new(400)
    [Text.Encoding]::ASCII.GetBytes('TGREVW01').CopyTo($frame,0); $frame[8]=[byte]$Action
    ([guid]::NewGuid().ToByteArray()).CopyTo($frame,16)
    if ($ClientId) { $id=[Text.Encoding]::ASCII.GetBytes($ClientId); $frame[9]=[byte]$id.Length; $id.CopyTo($frame,48) }
    if ($Sequence) { Put-Number $frame 32 $Sequence }
    if ($null -ne $Ticket) { $Ticket.CopyTo($frame,48) }
    $raw=Review $frame
    $reply=[byte[]]::new(432)
    for ($i=0;$i -lt 432;$i++) { $reply[$i]=[Convert]::ToByte($raw.Substring($i*2,2),16) }
    if ([Text.Encoding]::ASCII.GetString($reply,0,8) -cne 'TGREPLY1') { throw 'Review magic mismatch.' }
    for ($i=16;$i -lt 32;$i++) { if ($reply[$i] -ne $frame[$i]) { throw 'Uncorrelated review.' } }
    return ,$reply
}
if ($SelfTest) {
    $frame=[byte[]]::new(432)
    foreach ($number in @([uint64]1,[uint64]9007199254740993,[uint64]::MaxValue)) {
        Put-Number $frame 32 $number
        if ((Get-Number $frame 32) -ne $number) { throw 'Exact native integer round-trip failed.' }
    }
    function Review($Value) {
        if ($Value.Length -ne 400 -or $Value[8] -ne 5 -or $Value[9] -ne 8 -or
            [Text.Encoding]::ASCII.GetString($Value,48,8) -cne 'intent-1' -or (Get-Number $Value 32) -ne 9007199254740993) { throw 'Native request layout mismatch.' }
        $reply=[byte[]]::new(432)
        [Text.Encoding]::ASCII.GetBytes('TGREPLY1').CopyTo($reply,0)
        [Array]::Copy($Value,16,$reply,16,16)
        if ($script:badCorrelation) { $reply[16]=$reply[16] -bxor 255 }
        return ([BitConverter]::ToString($reply)).Replace('-','').ToLowerInvariant()
    }
    $script:badCorrelation=$false
    $reply=Request 5 'intent-1' 9007199254740993
    if ($reply.Length -ne 432) { throw 'Native receipt length changed.' }
    $script:badCorrelation=$true; $rejected=$false
    try { $null=Request 5 'intent-1' 9007199254740993 } catch { $rejected=$true }
    if (-not $rejected) { throw 'Uncorrelated response accepted.' }
    Write-Output 'PASS: exact u64 values, native frame layout and correlation rejection; no service or helper used.'
    return
}
# Select this shell's module rather than an inherited PS7 module path in a PS5 host.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run under the actual unelevated operator logon.' }
$code=Join-Path $env:ProgramFiles 'TradingGYM\Executor'
$manifestPath=Join-Path $code 'operator-qualification.json'
& (Join-Path $PSScriptRoot 'Assert-ExecutorDrillManifest.ps1') -Path $manifestPath
$manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
$age=[DateTime]::UtcNow-[DateTime]::Parse($manifest.created_utc).ToUniversalTime()
$service=Get-CimInstance Win32_Service -Filter "Name = 'TradingGYMExecutor'"
if ($manifest.user_sid -cne $identity.User.Value -or $manifest.capital_quanta -cne '0' -or
    $age.TotalSeconds -lt 0 -or $age.TotalMinutes -gt 3 -or $service.State -ne 'Running' -or $service.ProcessId -ne $manifest.service_pid) { throw 'Selected operator/current-runtime zero-budget attestation required.' }
if (-not $ReportPath -or (Test-Path -LiteralPath $ReportPath)) { throw 'New explicit qualification receipt required; existing files are preserved.' }
$report=[ordered]@{run_id=$manifest.run_id;at=[DateTime]::UtcNow.ToString('o');status='STARTING';user_sid=$identity.User.Value;service_pid=$service.ProcessId;account_api_called=$false;order_submitted=$false;funded_authority=$false}
try {
    $status=Request 1
    if ($status[8] -ne 1 -or $status[9] -ne 0 -or (Get-Number $status 56) -eq 0) { throw 'DISARMED service and recorded zero ceiling required.' }
    $id='probe-'+[guid]::NewGuid().ToString('N')
    $ticket=[byte[]]::new(352); $ticket[0]=2; $ticket[1]=8; $ticket[2]=2; $ticket[3]=6
    $values=@($id,'main','BTC','USDT'); $offsets=@(152,216,248,264)
    for ($i=0;$i -lt 4;$i++) { $name=[Text.Encoding]::ASCII.GetBytes($values[$i]); $ticket[4+$i]=[byte]$name.Length; $name.CopyTo($ticket,$offsets[$i]) }
    Put-Number $ticket 8 1 4; Put-Number $ticket 12 1 4
    Put-Number $ticket 16 (Get-Number $status 32); Put-Number $ticket 24 (Get-Number $status 56)
    Put-Number $ticket 32 ([uint64]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()+25000))
    Put-Number $ticket 40 100000000; Put-Number $ticket 48 100; Put-Number $ticket 64 1000000
    for ($i=72;$i -lt 136;$i++) { $ticket[$i]=1 }
    [Array]::Copy($status,64,$ticket,136,16)
    $approved=Request 3 '' 0 $ticket
    if ($approved[8] -ne 2) { throw 'Synthetic review was refused.' }
    $sequence=Get-Number $approved 40
    $prepared=Request 5 $id $sequence
    if ($prepared[8] -ne 7 -or (Get-Number $prepared 40) -le $sequence) { throw 'Prepare not committed.' }
    $sequence=Get-Number $prepared 40
    $duplicate=Request 5 $id $sequence
    if ($duplicate[8] -ne 6) { throw 'Duplicate preparation accepted.' }
    $inspected=Request 2 $id
    if ($inspected[8] -ne 7 -or (Get-Number $inspected 40) -ne $sequence) { throw 'Exact inspection failed.' }
    $revoked=Request 4 $id $sequence
    if ($revoked[8] -ne 3 -or (Get-Number $revoked 40) -le $sequence) { throw 'Revocation not committed.' }
    $report.client_id=$id; $report.review_prepared_and_revoked=$true
    $denials=& (Join-Path $PSScriptRoot 'Test-ResearchWorkerBoundary.ps1') -Launcher (Join-Path $code 'gym-research-worker.exe') -InstallDirectory $manifest.worker_install -ExistenceManifest $manifestPath
    $report.worker_denials=$denials
    $stops=@()
    foreach ($command in @('status','pause','exit-only','halt')) {
        $timer=[Diagnostics.Stopwatch]::StartNew(); $reply=& (Join-Path $code 'gym-stopctl.exe') $command; $timer.Stop()
        if ($LASTEXITCODE -ne 0 -or ($reply -join ' ') -notmatch '^ACKNOWLEDGED:' -or $timer.ElapsedMilliseconds -gt 1000) { throw 'STOP unacknowledged or exceeded one second.' }
        $stops+=@{command=$command;acknowledged=$true;elapsed_ms=$timer.ElapsedMilliseconds}
    }
    $report.stops=$stops; $report.status='PASSED'
} catch { $report.status='FAILED'; $report.error=$_.Exception.Message }
finally { [IO.File]::WriteAllText($ReportPath,($report|ConvertTo-Json -Depth 7)) }
if ($report.status -cne 'PASSED') { throw $report.error }
Write-Output 'PASS: ordinary operator review/prepare/duplicate-refusal/revoke, seven worker denials and four STOP acknowledgements.'
