@echo off
REM Double-click this to write the default URL to an NFC tag.
REM
REM   Write NFC Card.bat https://example.com   write a different URL
REM   Write NFC Card.bat --verify-only         show the tag's URL, write nothing
REM
REM _launch.bat finds whatever Python is installed on this machine, so no
REM interpreter path is hardcoded and this folder works on any computer.

setlocal
echo.
echo  Starting NFC writer...

set "NFC_SCRIPT=nfc_write.py"
call "%~dp0_launch.bat" %*
