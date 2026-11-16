@echo off
REM Builds a standalone Windows program: dist\msg2pdf.exe
REM Run from this folder after:  pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name msg2pdf ^
  --collect-all tkinterdnd2 ^
  --collect-data extract_msg ^
  --collect-data RTFDE ^
  msg2pdf_app.pyw
echo.
echo Done. Your program is in the dist folder.
pause
