@echo off
REM Double-click this to read an NFC card.
REM
REM   Read NFC Card.bat --watch       keep reading cards until closed
REM   Read NFC Card.bat --keys-only   UID and card type only, no memory dump
REM
REM _launch.bat finds whatever Python is installed on this machine, so no
REM interpreter path is hardcoded and this folder works on any computer.

setlocal
echo.
echo  Starting NFC reader...

set "NFC_SCRIPT=nfc_read.py"
call "%~dp0_launch.bat" %*
