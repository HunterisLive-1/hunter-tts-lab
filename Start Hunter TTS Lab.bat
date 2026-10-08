@echo off
setlocal
title Hunter TTS Lab - Built ^& customized by The Hunter AI
cd /d "%~dp0"

rem The app runs on a small private copy of Python kept in the runtime folder,
rem so nothing has to be installed on the PC and nothing already installed is
rem touched. It is fetched once from python.org and checked before use.
set "PY=runtime\python\python.exe"
set "PYVER=3.13.13"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYSHA=8766a8775746235e23cf5aee5027ab1060bb981d93110577adcf3508aa0cbd55"

if exist "%PY%" goto run

echo.
echo   Hunter TTS Lab - first start
echo   Built ^& customized by The Hunter AI
echo.
echo   Getting a small private copy of Python (11 MB). This happens once.
echo.
if not exist runtime mkdir runtime
curl.exe -L --fail --retry 3 --progress-bar -o "runtime\%PYZIP%" "https://www.python.org/ftp/python/%PYVER%/%PYZIP%"
if errorlevel 1 goto nodownload
powershell -NoProfile -ExecutionPolicy Bypass -Command "if ((Get-FileHash -Algorithm SHA256 'runtime\%PYZIP%').Hash -ne '%PYSHA%') { exit 1 }"
if errorlevel 1 goto badfile
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force 'runtime\%PYZIP%' 'runtime\python'"
if errorlevel 1 goto badfile
del "runtime\%PYZIP%"

:run
"%PY%" app\main.py %*
if errorlevel 1 pause
goto end

:nodownload
echo.
echo   Could not download Python. Check the internet connection and start again.
pause
goto end

:badfile
echo.
echo   The Python download was damaged. Start again to fetch it afresh.
del "runtime\%PYZIP%" 2>nul
pause

:end
endlocal
