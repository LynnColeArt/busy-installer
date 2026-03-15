@echo off
setlocal

set ROOT=%~dp0
set BOOTSTRAP=%ROOT%scripts\bootstrap_env.py
set VENV_PYTHON=%ROOT%.venv\Scripts\python.exe

where python3 >nul 2>nul
if %errorlevel%==0 (
  set PYTHON=python3
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set PYTHON=python
  ) else (
    echo Python 3 not found. Install Python 3.10+ and rerun. 1>&2
    exit /b 1
  )
)

%PYTHON% "%BOOTSTRAP%" >nul
"%VENV_PYTHON%" -m busy_installer.app %*
