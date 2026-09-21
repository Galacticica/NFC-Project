@echo off
REM Double-click this to see what a contactless bank card tells a reader.
REM
REM   Read Bank Card.bat --unmask   show the full card number on screen
REM                                 (last_emv.txt always keeps it masked)
REM
REM _launch.bat finds whatever Python is installed on this machine, so no
REM interpreter path is hardcoded and this folder works on any computer.

setlocal
echo.
echo  Starting bank card reader...

set "NFC_SCRIPT=nfc_emv.py"
call "%~dp0_launch.bat" %*
