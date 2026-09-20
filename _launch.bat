@echo off
REM ---------------------------------------------------------------------------
REM Shared launcher for the NFC scripts. Not meant to be run on its own -
REM double-click "Read NFC Card.bat" or "Write NFC Card.bat" instead.
REM
REM The caller sets NFC_SCRIPT to the Python file to run, then passes its own
REM arguments straight through:
REM
REM     set "NFC_SCRIPT=nfc_read.py"
REM     call "%~dp0_launch.bat" %*
REM
REM Passing the script name in a variable rather than as the first argument
REM keeps %* intact, so quoting survives: an argument such as "Acme & Co"
REM reaches Python whole. Rebuilding an argument list by hand does not survive
REM that, because the quotes in the value collide with the quotes around a
REM SET command and leave the & outside quoted state, where cmd reads it as a
REM command separator.
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

if not defined NFC_SCRIPT goto helper_only
if not exist "%HERE%%NFC_SCRIPT%" goto no_script

set "PYTHON="

REM A virtual environment in the project folder wins if one has been made.
if exist "%HERE%.venv\Scripts\python.exe" set PYTHON="%HERE%.venv\Scripts\python.exe"
if defined PYTHON goto check_pyscard

REM Otherwise the first candidate that can genuinely run Python.
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
%PYTHON% -u "%HERE%%NFC_SCRIPT%" %*
echo.
echo  ------------------------------------------------------------
echo   Finished.
echo  ------------------------------------------------------------
pause
exit /b 0

:no_python
echo.
echo   No working Python was found on this computer.
echo.
echo   Install Python 3 from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" during setup, then run this again.
echo.
pause
exit /b 1

:skipped_install
echo.
echo   Nothing was installed. To do it by hand:
echo       %PYTHON% -m pip install pyscard
echo.
pause
exit /b 1

:install_failed
echo.
echo   pip could not install pyscard - see the messages above.
echo.
pause
exit /b 1

:no_script
echo.
echo   Cannot find %NFC_SCRIPT% in:
echo       %HERE%
echo.
echo   Keep the .bat files in the same folder as the .py files.
echo.
pause
exit /b 1

:helper_only
echo.
echo   This is a helper script, not meant to be run on its own.
echo   Double-click "Read NFC Card.bat" or "Write NFC Card.bat" instead.
echo.
pause
exit /b 1
