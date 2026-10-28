@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
echo ATENCAO: O Windows pode bloquear o .exe gerado SEM assinatura digital.
echo Para uso pessoal, prefira ABRIR_AUTOFARM.cmd.
"%PYTHON%" -m pip install "pyinstaller>=6.15"
if errorlevel 1 goto erro
"%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name Roblox_AutoFarm_v10 --collect-submodules pynput --add-data "gravacoes;gravacoes" --add-data "referencias;referencias" main.py
if errorlevel 1 goto erro
echo.
echo Criado em: dist\Roblox_AutoFarm_v10.exe
pause
exit /b 0
:erro
echo Falha ao compilar.
pause
exit /b 1
