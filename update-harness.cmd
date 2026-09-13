@echo off
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%~dp0update.py" %*
) else (
  python "%~dp0update.py" %*
)
