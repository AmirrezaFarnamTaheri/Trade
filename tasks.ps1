<#
.SYNOPSIS
  Run the same checks as CI from a checkout (finding G-5). Windows PowerShell 5.1 or PowerShell 7.
.EXAMPLE
  .\tasks.ps1            # everything except the browser smoke
  .\tasks.ps1 rust python
  .\tasks.ps1 browser    # Edge or Chrome, synthetic data
  .\tasks.ps1 sbom       # CycloneDX SBOMs into .pi\sbom
  .\tasks.ps1 kernel     # build the optional Rust money kernel and run the suite on it
#>
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Task)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $Task) { $Task = @('rust', 'python', 'node') }

function Step([string]$Name, [scriptblock]$Body, [string]$Where = $root) {
    Write-Host "== $Name" -ForegroundColor Cyan
    Push-Location $Where
    try {
        & $Body
        if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
    } finally { Pop-Location }
}

$gym = Join-Path $root 'gym-core'
$tasks = @{
    rust   = {
        Step 'cargo fmt' { cargo fmt --all --check }
        Step 'cargo clippy' { cargo clippy --locked --workspace --all-targets -- -D warnings }
        Step 'cargo test' { cargo test --locked --workspace --all-targets }
    }
    python = {
        Step 'ruff' { uvx ruff==0.17.4 check src tests } $gym
        Step 'complexity ratchet' { python scripts/complexity_ratchet.py } $gym
        Step 'pytest' { uv run --no-sync pytest -q } $gym
    }
    node   = { Step 'model gateway tests' { npm test } (Join-Path $root 'model-gateway') }
    browser = { Step 'browser smoke' { node tests/browser_smoke.cjs } $gym }
    sbom   = {
        $out = Join-Path $root '.pi\sbom'
        New-Item -ItemType Directory -Force -Path $out | Out-Null
        Step 'python SBOM' { uv export --locked --format cyclonedx1.5 --no-dev -o (Join-Path $out 'python.cdx.json') } $gym
        Step 'node SBOM' {
            $json = npm sbom --sbom-format cyclonedx --omit dev
            [IO.File]::WriteAllText((Join-Path $out 'node.cdx.json'), ($json -join "`n"), (New-Object Text.UTF8Encoding $false))
        } (Join-Path $root 'model-gateway')
        Step 'rust SBOM' { python scripts/cargo_sbom.py -o (Join-Path $out 'rust.cdx.json') }
        Write-Host "SBOMs in $out"
    }
    kernel = {
        Step 'kernel wheel' { uvx --from 'maturin>=1.7,<2' maturin build --release -m ../executor/exec-kernel-py/Cargo.toml -o dist } $gym
        Step 'install kernel' { $wheel = Get-ChildItem (Join-Path $gym 'dist\exec_kernel-*.whl') | Select-Object -Last 1; uv pip install --no-deps --reinstall $wheel.FullName } $gym
        Step 'pytest on the Rust kernel' { $env:GYM_RUST_KERNEL = '1'; try { uv run --no-sync pytest -q } finally { Remove-Item Env:GYM_RUST_KERNEL } } $gym
    }
}

foreach ($name in $Task) {
    if (-not $tasks.ContainsKey($name)) { throw "unknown task '$name'; choose from $($tasks.Keys -join ', ')" }
    & $tasks[$name]
}
Write-Host 'All requested tasks passed.' -ForegroundColor Green
