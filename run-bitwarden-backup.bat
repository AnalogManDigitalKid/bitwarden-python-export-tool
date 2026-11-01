@echo off
rem Double-click launcher for bitwarden_backup.py
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0bitwarden_backup.py" %*
) else (
    python "%~dp0bitwarden_backup.py" %*
)
pause
