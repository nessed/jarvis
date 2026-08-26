@echo off
REM Double-click this to run JARVIS. Closing the window, or Ctrl+C, stops it.
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
