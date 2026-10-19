# SyncFlow security suite - Windows runner (mirrors run_all.sh).
# Starts two fresh backend instances (A: TCP 19974 / WS 18993,
# B: TCP 19975 / WS 18995), runs all twelve suites against them, prints a
# PASS/FAIL summary and tears everything down. Exit code 0 = all green.
#
# Usage:  powershell -ExecutionPolicy Bypass -File backend\tests\run_all.ps1
$ErrorActionPreference = 'Continue'

$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND = Resolve-Path (Join-Path $HERE '..')
$PY = Join-Path $BACKEND 'venv\Scripts\python.exe'
if (-not (Test-Path $PY)) {
    $PY = (Get-Command python).Source
}
# Same artifact dir as the POSIX runner and proto_lib.py.
$ART = '/tmp/opencode'
New-Item -ItemType Directory -Force -Path $ART | Out-Null

Write-Host '=== SyncFlow security suite (Windows) ==='
Write-Host "python: $PY"

# --- fresh state ------------------------------------------------------
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue @(
    "$ART/sfA", "$ART/sfB", "$ART/sfT", "$ART/sfOTHER", "$ART/sfM", "$ART/sfATK",
    "$ART/sfPin", "$ART/sfPinOther", "$ART/sfDN"
)
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue @(
    "$HOME\Downloads\SyncFlow-testA", "$HOME\Downloads\SyncFlow-testB",
    "$HOME\Downloads\SyncFlow-testDN"
)

function Wait-Port {
    param([int]$Port, $Proc, [int]$Tries = 60)
    for ($i = 0; $i -lt $Tries; $i++) {
        if ($Proc.HasExited) { return $false }
        $c = New-Object Net.Sockets.TcpClient
        try {
            $c.Connect('127.0.0.1', $Port)
            $c.Close()
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Test-Port {
    param([int]$Port)
    $c = New-Object Net.Sockets.TcpClient
    try {
        $c.Connect('127.0.0.1', $Port)
        $c.Close()
        return $true
    } catch {
        return $false
    }
}

# --- start instances --------------------------------------------------
$env:SYNCFLOW_HOME = "$ART/sfA"; $env:SYNCFLOW_TCP_PORT = '19974'; $env:SYNCFLOW_WS_PORT = '18993'
$a = Start-Process -FilePath $PY -ArgumentList '-u', "`"$BACKEND\main.py`"" `
    -WorkingDirectory $BACKEND -RedirectStandardOutput "$ART/A.log" `
    -RedirectStandardError "$ART/A.err.log" -PassThru -NoNewWindow

$env:SYNCFLOW_HOME = "$ART/sfB"; $env:SYNCFLOW_TCP_PORT = '19975'; $env:SYNCFLOW_WS_PORT = '18995'
$b = Start-Process -FilePath $PY -ArgumentList '-u', "`"$BACKEND\main.py`"" `
    -WorkingDirectory $BACKEND -RedirectStandardOutput "$ART/B.log" `
    -RedirectStandardError "$ART/B.err.log" -PassThru -NoNewWindow

$okA = Wait-Port -Port 19974 -Proc $a
$okB = Wait-Port -Port 19975 -Proc $b
$okW = Test-Port -Port 18993
if (-not $okA -or -not $okB -or -not $okW) {
    Write-Host 'FATAL: instances did not open their ports:'
    if (Test-Path "$ART/A.log") { Get-Content "$ART/A.log" }
    if (Test-Path "$ART/A.err.log") { Get-Content "$ART/A.err.log" }
    if (Test-Path "$ART/B.log") { Get-Content "$ART/B.log" }
    Stop-Process -Id $a.Id, $b.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Start-Sleep 4  # let mDNS register/browse settle

$TOTAL_PASS = 0
$TOTAL_FAIL = 0

$suites = @(
    @{ label = 't_net';        args = @("$HERE\t_net.py", "$($a.Id)") },
    @{ label = 't_proto';      args = @("$HERE\t_proto.py") },
    @{ label = 'mitm2';        args = @("$HERE\mitm2.py") },
    @{ label = 't_ws';         args = @("$HERE\t_ws.py") },
    @{ label = 't_mdns_rogue'; args = @("$HERE\t_mdns_rogue.py") },
    @{ label = 't_extra';      args = @("$HERE\t_extra.py") },
    @{ label = 't_attacks';    args = @("$HERE\t_attacks.py") },
    @{ label = 't_crypto';     args = @("$HERE\t_crypto.py") },
    @{ label = 't_lan_auth';   args = @("$HERE\t_lan_auth.py") },
    @{ label = 't_upload';     args = @("$HERE\t_upload.py") },
    @{ label = 't_download';   args = @("$HERE\t_download.py") },
    @{ label = 't_fuzz';       args = @("$HERE\t_fuzz.py") }
)

try {
    foreach ($s in $suites) {
        Write-Host ''
        Write-Host "########## $($s.label) ##########"
        $out = & $PY -u @($s.args) 2>&1
        $rc = $LASTEXITCODE
        $text = ($out | Out-String)
        $out | Tee-Object -FilePath "$ART/$($s.label).out" | Write-Host
        $p = ([regex]::Matches($text, '(?m)^PASS ')).Count
        $f = ([regex]::Matches($text, '(?m)^FAIL ')).Count
        # A crashed suite emits neither PASS nor FAIL lines — never let that
        # read as green: nonzero exit without FAIL lines counts as a failure.
        if ($rc -ne 0 -and $f -eq 0) {
            Write-Host "FAIL suite $($s.label) exited $rc without results (crash?)"
            $f = 1
        }
        $TOTAL_PASS += $p
        $TOTAL_FAIL += $f
    }
} finally {
    Stop-Process -Id $a.Id, $b.Id -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '======================================'
Write-Host "TOTAL PASS: $TOTAL_PASS   TOTAL FAIL: $TOTAL_FAIL"
if ($TOTAL_FAIL -eq 0 -and $TOTAL_PASS -gt 0) {
    Write-Host 'ALL GREEN'
    exit 0
}
Write-Host 'FAILURES PRESENT'
exit 1
