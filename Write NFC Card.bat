@echo off
REM Double-click this to write the URL to an NFC card.
REM Pins the Python that has pyscard installed, so editor settings don't matter.

cd /d "%~dp0"

echo Starting NFC writer...
echo.

"C:\Users\reaga\AppData\Local\Microsoft\WindowsApps\python.exe" -u nfc_write.py %*

echo.
echo ------------------------------------------------------------
echo Finished. Results were also saved to last_write.txt
echo ------------------------------------------------------------
pause
