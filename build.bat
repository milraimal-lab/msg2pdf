@echo off
REM Builds dist\msg2pdf.exe on your own PC. Just double-click this file.
REM It uses a WinPython folder (WPy64-*) next to this one, or the python on PATH.
setlocal
cd /d "%~dp0"

set "PY="
REM 1) WinPython next to this folder, e.g. F:\Py\WPy64-3.13.12.0
for /d %%D in ("%~dp0..\WPy64-*") do (
    if exist "%%D\python\python.exe" set "PY=%%D\python\python.exe"
)
REM 2) otherwise a real Python on PATH (not the Microsoft Store shortcut)
if not defined PY (
    python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Could not find Python.
    echo Put WinPython next to this folder, or run this from "WinPython Command Prompt.exe".
    goto :error
)
echo Using Python: %PY%

"%PY%" -m pip install -r requirements.txt pyinstaller || goto :error
"%PY%" -m PyInstaller --noconfirm --clean msg2pdf.spec || goto :error
echo.
echo Done: %~dp0dist\msg2pdf.exe
pause
exit /b 0

:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
