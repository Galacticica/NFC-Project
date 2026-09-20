@echo off
REM Double-click this to read an NFC card.
REM It pins the exact Python that has pyscard installed, so it does not
REM matter what interpreter an editor happens to be configured with.

cd /d "%~dp0"

echo Starting NFC reader...
echo.

"C:\Users\reaga\AppData\Local\Microsoft\WindowsApps\python.exe" -u nfc_read.py %*

echo.
echo ------------------------------------------------------------
echo Finished. Results were also saved to last_read.txt
echo ------------------------------------------------------------
pause
