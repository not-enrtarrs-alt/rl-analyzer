[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot 'run_daily.ps1'
$TaskName = 'RL Analyzer Daily'
$Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $Runner
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At '19:00'
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)

if ($PSCmdlet.ShouldProcess($TaskName, 'Install or update daily task')) {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
    Write-Output "Installed or updated '$TaskName' for 19:00 local time."
}
