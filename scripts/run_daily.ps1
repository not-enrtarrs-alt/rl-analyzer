[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'logs'
$LogPath = Join-Path $LogDir 'scheduler.log'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-LogLine([string]$Message) {
    $line = '{0} {1}{2}' -f ([DateTimeOffset]::UtcNow.ToString('o')), $Message, [Environment]::NewLine
    [System.IO.File]::AppendAllText($LogPath, $line, $Utf8)
}

try {
    [System.IO.Directory]::CreateDirectory($LogDir) | Out-Null
    Write-LogLine 'Starting scheduled RL Analyzer run.'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        Write-LogLine 'ERROR: Project virtual environment Python was not found.'
        exit 6
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $Python
    $start.Arguments = '-m rl_analyzer run'
    $start.WorkingDirectory = $Root
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $Utf8
    $start.StandardErrorEncoding = $Utf8
    $start.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Unable to start Python.' }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    foreach ($line in ($stdout.Result -split "`r?`n")) { if ($line) { Write-LogLine "OUT $line" } }
    foreach ($line in ($stderr.Result -split "`r?`n")) { if ($line) { Write-LogLine "ERR $line" } }
    $code = $process.ExitCode
    $process.Dispose()
    Write-LogLine "Finished with exit code $code."
    exit $code
} catch {
    try { Write-LogLine 'ERROR: Scheduler wrapper failed.' } catch { }
    exit 6
}
