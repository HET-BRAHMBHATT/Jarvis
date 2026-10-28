@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE="
for /d %%D in ("%LocalAppData%\Python\pythoncore-*") do if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('where.exe python.exe 2^>nul') do (
    echo "%%P" | findstr /i "\\WindowsApps\\" >nul
    if errorlevel 1 if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
  )
)
if not defined PYTHON_EXE (
  echo Could not find Python 3.10 or newer.
  echo Install Python, then try this file again.
  pause
  exit /b 1
)
echo Starting J.A.R.V.I.S. with "%PYTHON_EXE%" ...
"%PYTHON_EXE%" -u "%~dp0server.py" %*
if errorlevel 1 (
  echo.
  echo J.A.R.V.I.S. stopped with an error. Read the message above.
  pause
)
endlocal

