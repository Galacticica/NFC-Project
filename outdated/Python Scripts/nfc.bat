@echo off
REM ---------------------------------------------------------------------------
REM One launcher for every NFC script in this folder.
REM
REM Double-click it and pick a number from the menu, or run it from a terminal
REM with the job as the first argument and the script's own options after:
REM
REM     nfc.bat read --watch
REM     nfc.bat write https://example.com
REM     nfc.bat bank --unmask
REM     nfc.bat help
REM
REM Arguments after the job name are handed to Python untouched, so quoting
REM survives: nfc.bat write --vcard --name "Acme & Co" arrives whole. That is
REM why the loop below rebuilds the list one argument at a time with the plain
REM SET form. The quoted form, set "ARGS=%ARGS% %1", would put the value's own
REM quotes next to the quotes around the assignment; the pairing shifts, the &
REM ends up outside quoted state, and cmd reads it as a command separator.
REM
REM Which Python to use is worked out at run time rather than being baked in,
REM so this folder can be copied to any computer. Each candidate is tested by
REM actually importing with it: that is what rules out the Microsoft Store
REM alias stub at C:\...\WindowsApps\python.exe, which sits on PATH looking
REM like a real interpreter but only ever prints "Python was not found".
REM Checking whether the file exists is not enough to catch it.
REM ---------------------------------------------------------------------------

setlocal EnableExtensions

set "HERE=%~dp0"
set "INTERACTIVE="
set "ARGS="

set "JOB=%~1"
if not defined JOB goto menu
shift

:collect
if "%~1"=="" goto resolve
set ARGS=%ARGS% "%~1"
shift
goto collect

REM ---------------------------------------------------------------------------
REM  Double-clicked: no arguments, so ask which job to run.
REM ---------------------------------------------------------------------------
:menu
set "INTERACTIVE=1"
echo.
echo   NFC toolkit
echo   -----------
echo     1.  Read an NFC card
echo     2.  Write a URL to an NFC tag
echo     3.  Copy one tag onto another
echo     4.  Clear a tag so it reads as blank
echo     5.  Read a contactless bank card
echo.
set "CHOICE="
set /p "CHOICE=  Pick a number [1-5]: "

if "%CHOICE%"=="1" set "JOB=read"
if "%CHOICE%"=="2" set "JOB=write"
if "%CHOICE%"=="3" set "JOB=copy"
if "%CHOICE%"=="4" set "JOB=clear"
if "%CHOICE%"=="5" set "JOB=bank"

if not defined JOB goto bad_choice

REM ---------------------------------------------------------------------------
REM  Job name to Python file.
REM ---------------------------------------------------------------------------
:resolve
if /i "%JOB%"=="help" goto usage
if /i "%JOB%"=="--help" goto usage
if /i "%JOB%"=="-h" goto usage
if /i "%JOB%"=="/?" goto usage

set "NFC_SCRIPT="
set "BANNER="

if /i "%JOB%"=="read" (
    set "NFC_SCRIPT=nfc_read.py"
    set "BANNER=Starting NFC reader..."
)
if /i "%JOB%"=="write" (
    set "NFC_SCRIPT=nfc_write.py"
    set "BANNER=Starting NFC writer..."
)
if /i "%JOB%"=="copy" (
    set "NFC_SCRIPT=nfc_copy.py"
    set "BANNER=Starting NFC copier..."
)
if /i "%JOB%"=="clear" (
    set "NFC_SCRIPT=nfc_clear.py"
    set "BANNER=Starting NFC eraser..."
)
if /i "%JOB%"=="bank" (
    set "NFC_SCRIPT=nfc_emv.py"
    set "BANNER=Starting bank card reader..."
)
REM The same job under the name the Python file uses.
if /i "%JOB%"=="emv" (
    set "NFC_SCRIPT=nfc_emv.py"
    set "BANNER=Starting bank card reader..."
)

if not defined NFC_SCRIPT goto unknown_job
if not exist "%HERE%%NFC_SCRIPT%" goto no_script

echo.
echo  %BANNER%

REM ---------------------------------------------------------------------------
REM  Find a Python that actually runs.
REM ---------------------------------------------------------------------------
set "PYTHON="

REM A virtual environment in the project folder wins if one has been made.
if exist "%HERE%.venv\Scripts\python.exe" set PYTHON="%HERE%.venv\Scripts\python.exe"
if defined PYTHON goto check_pyscard

py -3 -c "import sys" >nul 2>&1 && set "PYTHON=py -3"
if defined PYTHON goto check_pyscard

python -c "import sys" >nul 2>&1 && set "PYTHON=python"
if defined PYTHON goto check_pyscard

python3 -c "import sys" >nul 2>&1 && set "PYTHON=python3"
if defined PYTHON goto check_pyscard

goto no_python

:check_pyscard
REM pyscard is what talks to the PC/SC reader; nothing works without it.
%PYTHON% -c "import smartcard" >nul 2>&1
if not errorlevel 1 goto run

echo.
echo   The pyscard package is missing for this Python:
%PYTHON% -c "import sys; print('     ' + sys.executable)"
echo.
set "INSTALL="
set /p "INSTALL=  Install it now? [y/N] "
if /i not "%INSTALL%"=="y" goto skipped_install
echo.
REM Some Python installs ship without pip until it is bootstrapped.
%PYTHON% -m pip --version >nul 2>&1 || %PYTHON% -m ensurepip --upgrade
%PYTHON% -m pip install pyscard
if errorlevel 1 goto install_failed
echo.

:run
cd /d "%HERE%"
%PYTHON% -u "%HERE%%NFC_SCRIPT%"%ARGS%
set "RC=%ERRORLEVEL%"
echo.
echo  ------------------------------------------------------------
echo   Finished.
echo  ------------------------------------------------------------
call :wait
exit /b %RC%

REM ---------------------------------------------------------------------------
REM  Help and errors.
REM ---------------------------------------------------------------------------
:usage
echo.
echo   nfc.bat ^<job^> [options]
echo.
echo   Jobs:
echo     read    dump an NFC card               -^> last_read.txt
echo     write   write a URL or vCard to a tag  -^> last_write.txt
echo     copy    copy one tag onto another      -^> last_copy.txt
echo     clear   erase a tag, backing it up first
echo     bank    read a contactless bank card   -^> last_emv.txt
echo.
echo   Common options (every job also takes --reader NAME):
echo     read    --watch          keep reading tags until closed
echo             --keys-only      UID and card type only, no memory dump
echo     write   URL              write a different URL
echo             --verify-only    show the tag's URL, write nothing
echo             --uid HEX        only write if the tag's UID matches
echo             --vcard --name "Jane Doe" --phone ... --email ...
echo     copy    --yes            do not ask before overwriting the target
echo     clear   --yes            do not ask before erasing
echo     bank    --unmask         full card number on screen (log stays masked)
echo.
echo   Run nfc.bat with no arguments for a menu, or
echo   nfc.bat ^<job^> --help for that script's own full option list.
echo.
call :wait
exit /b 0

:unknown_job
echo.
echo   Unknown job: %JOB%
echo.
echo   Expected one of: read, write, copy, clear, bank
echo   Run nfc.bat help for the full list.
echo.
call :wait
exit /b 1

:bad_choice
echo.
echo   That was not one of the numbers. Nothing was run.
echo.
call :wait
exit /b 1

:no_python
echo.
echo   No working Python was found on this computer.
echo.
echo   Install Python 3 from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" during setup, then run this again.
echo.
call :wait
exit /b 1

:skipped_install
echo.
echo   Nothing was installed. To do it by hand:
echo       %PYTHON% -m pip install pyscard
echo.
call :wait
exit /b 1

:install_failed
echo.
echo   pip could not install pyscard - see the messages above.
echo.
call :wait
exit /b 1

:no_script
echo.
echo   Cannot find %NFC_SCRIPT% in:
echo       %HERE%
echo.
echo   Keep nfc.bat in the same folder as the .py files.
echo.
call :wait
exit /b 1

REM A double-clicked window closes the moment the script ends, so hold it open
REM long enough to read. Started from a terminal there is nothing to hold.
:wait
if defined INTERACTIVE pause
exit /b 0
