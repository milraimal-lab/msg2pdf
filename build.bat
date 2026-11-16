@echo off
REM Builds dist\msg2pdf.exe on your own PC.
REM Run it from a Python command prompt (e.g. "WinPython Command Prompt.exe"):
REM     cd /d F:\Py\msg2pdf
REM     build.bat
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller --noconfirm --clean msg2pdf.spec || goto :error
echo.
echo Done: %~dp0dist\msg2pdf.exe
pause
exit /b 0
:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
