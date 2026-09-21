@echo off
REM Double-click this to copy one NFC tag onto another.
REM Tap the source card first, then the target card when asked.
REM
REM   Copy NFC Card.bat --yes     do not ask before overwriting the target
REM
REM _launch.bat finds whatever Python is installed on this machine, so no
REM interpreter path is hardcoded and this folder works on any computer.

setlocal
echo.
echo  Starting NFC copier...

set "NFC_SCRIPT=nfc_copy.py"
call "%~dp0_launch.bat" %*
