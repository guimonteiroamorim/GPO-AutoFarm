@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%PYTHON%" goto found
where python >nul 2>&1
if errorlevel 1 goto no_python
set "PYTHON=python"
:found
"%PYTHON%" main.py
if errorlevel 1 (
 echo.
 echo O programa encerrou com erro. Copie a mensagem acima para o ChatGPT.
 pause
)
exit /b 0
:no_python
echo Python nao encontrado. Instale o Python primeiro.
pause
exit /b 1
