@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" -m unittest -v test_relogio_manual.py
pause
