@echo off
setlocal

set ROOT=%~dp0
set BOOTSTRAP=%ROOT%scripts\bootstrap_env.py
set VENV_PYTHON=%ROOT%.venv\Scripts\python.exe

if exist "%VENV_PYTHON%" (
  set PYTHON=%VENV_PYTHON%
) else (
  where python3 >nul 2>nul
  if %errorlevel%==0 (
    set PYTHON=python3
  ) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
      set PYTHON=python
    ) else (
      echo Python 3 not found and %VENV_PYTHON% is missing. Install Python 3.10+ and rerun. 1>&2
      exit /b 1
    )
  )
)

"%PYTHON%" "%BOOTSTRAP%" >nul
if not exist "%VENV_PYTHON%" (
  echo bootstrap completed but %VENV_PYTHON% is missing. 1>&2
  exit /b 1
)

"%VENV_PYTHON%" -m busy_installer.app %*
