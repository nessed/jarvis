@echo off
REM Double-click this to run JARVIS. Ctrl+C stops it, and so does closing
REM the window: every child is in a kill-on-close Windows job object, so the
REM OS takes the whole tree down with this process however it dies.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "JARVIS_PY=.venv\Scripts\python.exe"
) else (
    set "JARVIS_PY=python"
)

"%JARVIS_PY%" tools\start_jarvis.py %*

echo.
echo JARVIS has stopped.
pause
