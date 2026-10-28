@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo    Roblox AutoFarm - Compilar App
 echo ========================================

where py >nul 2>nul
if not errorlevel 1 (
  set "PY=py -3.14"
) else (
  set "PY=python"
)

%PY% --version
if errorlevel 1 goto erro
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto erro
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto erro

%PY% -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name RobloxAutoFarm --collect-submodules pynput --add-data "gravacoes;gravacoes" --add-data "referencias;referencias" main.py
if errorlevel 1 goto erro

echo.
echo Aplicativo criado em dist\RobloxAutoFarm\RobloxAutoFarm.exe
echo Teste-o antes de criar o instalador!
pause
exit /b 0

:erro
echo.
echo ERRO na compilacao. Veja a mensagem acima.
pause
exit /b 1
