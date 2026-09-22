@echo off
REM Double-click this to erase an NFC tag so it reads as blank.
REM The tag is backed up to backup_<UID>.txt first, so it can be restored.
REM
REM   Clear NFC Card.bat --yes     do not ask before erasing
REM
REM _launch.bat finds whatever Python is installed on this machine, so no
REM interpreter path is hardcoded and this folder works on any computer.

setlocal
echo.
echo  Starting NFC eraser...

set "NFC_SCRIPT=nfc_clear.py"
call "%~dp0_launch.bat" %*
