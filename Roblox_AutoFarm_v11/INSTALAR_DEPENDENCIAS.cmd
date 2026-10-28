@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%PYTHON%" goto found
where python >nul 2>&1
if errorlevel 1 goto no_python
set "PYTHON=python"
:found
echo Instalando bibliotecas do Roblox AutoFarm v10...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
 echo.
 echo Falha ao instalar bibliotecas. Copie esta mensagem para o ChatGPT.
 pause
 exit /b 1
)
echo.
echo Dependencias instaladas. Abra ABRIR_AUTOFARM.cmd
pause
exit /b 0
:no_python
echo Python nao foi encontrado. Instale o Python primeiro.
pause
exit /b 1
