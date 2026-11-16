[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$TaskName = 'RL Analyzer Daily'
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $Existing) {
    Write-Output "'$TaskName' is not installed."
    return
}
if ($PSCmdlet.ShouldProcess($TaskName, 'Remove daily task')) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed '$TaskName'."
}
