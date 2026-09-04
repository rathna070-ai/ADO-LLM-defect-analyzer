@echo off
REM One-command launcher for Windows.
REM
REM Creates a virtual environment beside this script on first run, installs the
REM package into it, and starts the dashboard. Safe to re-run: an existing
REM environment is reused, so the slow path happens once.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required but was not found on PATH.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  exit /b 1
)

if not exist ".venv" (
  echo Creating a virtual environment in .venv ...
  python -m venv .venv
  if errorlevel 1 exit /b 1
)

echo Installing the analyzer and its dashboard ...
call ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
call ".venv\Scripts\python.exe" -m pip install --quiet -e ".[dashboard]"
if errorlevel 1 exit /b 1

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo.
  echo Created .env from the template. Add your LLM key before running an analysis:
  echo     ado-defect-analysis secrets set GROQ_API_KEY
  echo.
)

echo Starting the dashboard on http://localhost:8501 ...
call ".venv\Scripts\ado-defect-analysis.exe" dashboard %*
