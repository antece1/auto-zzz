# ZZZ AutoBetterZZZ
# 1) close BetterGI and Genshin Impact, 2) close leftover OneDragon windows,
# 3) push today's farming plan into the OneDragon charge plan (planner\daily\push_plan.py),
# 4) run the ZZZ OneDragon daily run (-o) and close ZZZ when done (-c).
# Started by the Task Scheduler job "ZZZ OneDragon Daily 2330" (daily 23:00 since 2026-11-21; name kept)
# and by the desktop shortcut "ZZZ AutoBetterZZZ" (which just runs that job).
# Keep this file ASCII-only (Windows PowerShell 5.1 misreads UTF-8 without BOM).
param([switch]$DryRun)

try { $Host.UI.RawUI.WindowTitle = 'ZZZ AutoBetterZZZ - do not touch mouse/keyboard while it runs' } catch {}

$root = if ($env:ONEDRAGON_DIR) { $env:ONEDRAGON_DIR } else { 'C:\ZZZ-OneDragon' }
$log  = Join-Path $PSScriptRoot 'run_daily.log'
$genshinNames = @('BetterGI', 'GenshinImpact', 'YuanShen')

function Write-Log([string]$msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    if (-not $DryRun) { try { Add-Content -Path $log -Value $line -Encoding UTF8 } catch {} }
}

function Close-Process($proc) {
    Write-Log ('Closing {0} (pid {1})' -f $proc.Name, $proc.Id)
    if (-not $DryRun) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}

Write-Log ('===== ZZZ AutoBetterZZZ start' + $(if ($DryRun) { ' (dry run, nothing is closed or started)' } else { '' }) + ' =====')

# 1. BetterGI first, so it cannot keep driving or reopen Genshin; then Genshin itself
foreach ($name in $genshinNames) {
    foreach ($p in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) { Close-Process $p }
}

# 2. Leftover OneDragon processes (control panel GUI, commission assistant, ...)
$odProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ExecutablePath -like "$root\*" })
foreach ($p in $odProcs) {
    Write-Log ('Closing old OneDragon process {0} (pid {1})' -f $p.Name, $p.ProcessId)
    if (-not $DryRun) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
}

# 3. Push today's farming plan (planner\daily\push_plan.py) into config\01\one_dragon\charge_plan.yml.
#    A failure here is logged and the run goes on with the charge plan as it was.
$push = Join-Path (Split-Path $PSScriptRoot -Parent) 'daily\push_plan.py'
$py = "$root\.venv\Scripts\python.exe"
if ((Test-Path $push) -and (Test-Path $py)) {
    $pushArgs = @('-I', $push)
    if ($DryRun) { $pushArgs += '--dry-run' }
    try {
        $out = & $py @pushArgs 2>&1 | Out-String
        foreach ($l in ($out -split "`r?`n")) { if ($l.Trim()) { Write-Log ('push_plan: ' + $l.Trim()) } }
        if ($LASTEXITCODE -ne 0) { Write-Log ('WARNING: push_plan exited with code ' + $LASTEXITCODE + '; charge plan left as it was') }
    } catch { Write-Log ('WARNING: push_plan failed: ' + $_) }
} else {
    Write-Log 'push_plan.py or OneDragon python not found; charge plan left as it was'
}

if ($DryRun) {
    Write-Log 'Dry run: would now start OneDragon-Launcher.exe -o -c'
    exit 0
}

# Wait up to 30 seconds for everything to exit
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Process -Name $genshinNames -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
    Start-Sleep -Seconds 1
}
$left = @(Get-Process -Name $genshinNames -ErrorAction SilentlyContinue)
if ($left.Count -gt 0) {
    Write-Log ('WARNING: still running after 30s: ' + (($left | ForEach-Object { $_.Name }) -join ', '))
} else {
    Write-Log 'Genshin Impact and BetterGI are closed.'
}
Start-Sleep -Seconds 3

# 4. Run the ZZZ one-dragon (it starts the game itself) and close the game afterwards
Set-Location $root
Write-Log 'Starting ZZZ OneDragon: OneDragon-Launcher.exe -o -c'
& "$root\OneDragon-Launcher.exe" -o -c
$code = $LASTEXITCODE
Write-Log ('ZZZ OneDragon finished, exit code ' + $code)
exit $code
