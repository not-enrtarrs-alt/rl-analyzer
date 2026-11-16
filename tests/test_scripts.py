"""Windows scheduler scripts are tested without registering a real task."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell scheduler scripts")


def powershell(code: str, *, env=None):
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
                          text=True, capture_output=True, encoding="utf-8", env=env, timeout=30)


def ps_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def test_install_updates_same_task_with_required_settings():
    code = r'''
$global:registrations = @()
function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory) return @{execute=$Execute;argument=$Argument;working=$WorkingDirectory} }
function New-ScheduledTaskTrigger { param([switch]$Daily,$At) return @{daily=[bool]$Daily;at=$At} }
function New-ScheduledTaskSettingsSet { param([switch]$StartWhenAvailable,$MultipleInstances,$ExecutionTimeLimit) return @{start=[bool]$StartWhenAvailable;multiple=$MultipleInstances;hours=$ExecutionTimeLimit.TotalHours} }
function Register-ScheduledTask { param($TaskName,$Action,$Trigger,$Settings,[switch]$Force) $global:registrations += @{name=$TaskName;action=$Action;trigger=$Trigger;settings=$Settings;force=[bool]$Force} }
& SCRIPT | Out-Null
& SCRIPT | Out-Null
ConvertTo-Json -InputObject $global:registrations -Depth 6 -Compress
'''.replace("SCRIPT", ps_path(SCRIPTS / "install_task.ps1"))
    result = powershell(code)
    assert result.returncode == 0, result.stderr
    runs = json.loads(result.stdout)
    assert len(runs) == 2 and runs[0] == runs[1]
    run = runs[0]
    assert run["name"] == "RL Analyzer Daily" and run["force"]
    assert run["trigger"] == {"daily": True, "at": "19:00"}
    assert run["settings"] == {"start": True, "multiple": "IgnoreNew", "hours": 1}
    assert run["action"]["working"] == str(ROOT)
    assert run["action"]["execute"] == "powershell.exe"
    assert f'"{SCRIPTS / "run_daily.ps1"}"' in run["action"]["argument"]


def test_uninstall_is_safe_when_task_absent():
    code = r'''
$global:exists = $true
$global:removed = 0
function Get-ScheduledTask { [CmdletBinding()] param($TaskName) if ($global:exists) { return @{name=$TaskName} } }
function Unregister-ScheduledTask { [CmdletBinding(SupportsShouldProcess=$true)] param($TaskName) $global:removed++; $global:exists=$false }
& SCRIPT | Out-Null
& SCRIPT | Out-Null
Write-Output $global:removed
'''.replace("SCRIPT", ps_path(SCRIPTS / "uninstall_task.ps1"))
    result = powershell(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_runner_logs_streams_and_returns_python_exit_code(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SCRIPTS / "run_daily.ps1", scripts / "run_daily.ps1")
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    shutil.copy2(sys.executable, python_path)
    shutil.copy2(ROOT / ".venv" / "pyvenv.cfg", tmp_path / ".venv" / "pyvenv.cfg")
    fake_package = tmp_path / "fake" / "rl_analyzer"
    fake_package.mkdir(parents=True)
    (fake_package / "__init__.py").write_text("", encoding="utf-8")
    (fake_package / "__main__.py").write_text("import sys\nprint('stdout test')\nprint('stderr test', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(fake_package.parent)}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "run_daily.ps1")],
                            text=True, capture_output=True, encoding="utf-8", env=env, timeout=30)
    assert result.returncode == 7, result.stderr
    data = (tmp_path / "logs" / "scheduler.log").read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    log = data.decode("utf-8")
    assert "OUT stdout test" in log and "ERR stderr test" in log and "exit code 7" in log
    assert all(line.startswith("20") and "T" in line for line in log.splitlines())
