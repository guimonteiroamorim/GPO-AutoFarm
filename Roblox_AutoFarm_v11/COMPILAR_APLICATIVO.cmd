@echo off
setlocal
cd /d "%~dp0"
title Compilar GPO_AutoFarm_v11 (ambiente isolado)

echo ==========================================
echo  Compilacao limpa - GPO_AutoFarm_v11
echo ==========================================
echo.

if exist "%~dp0.build-venv\Scripts\python.exe" goto have_venv

echo [1/4] Criando ambiente isolado...
py -3.14 -m venv ".build-venv" 2>nul
if not errorlevel 1 goto have_venv
py -3 -m venv ".build-venv" 2>nul
if not errorlevel 1 goto have_venv
python -m venv ".build-venv"
if errorlevel 1 goto error

:have_venv
set "PY=%~dp0.build-venv\Scripts\python.exe"
if not exist "%PY%" goto error

echo [2/4] Instalando apenas dependencias do projeto...
"%PY%" -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
if errorlevel 1 goto error

echo [3/4] Instalando PyInstaller no ambiente isolado...
"%PY%" -m pip install --disable-pip-version-check --no-cache-dir "pyinstaller>=6.17"
if errorlevel 1 goto error

echo [4/4] Compilando executavel enxuto...
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name GPO_AutoFarm_v11 --collect-submodules pynput --exclude-module pandas --exclude-module pyarrow --exclude-module numpy --exclude-module scipy --exclude-module matplotlib --exclude-module cv2 --add-data "gravacoes\gravacao_coleta_1.rec;gravacoes" --add-data "gravacoes\gravacao_analise_2.rec;gravacoes" --add-data "gravacoes\gravacao_compra_3.rec;gravacoes" main.py
if errorlevel 1 goto error

echo.
echo SUCESSO! Abra dist\GPO_AutoFarm_v11\GPO_AutoFarm_v11.exe para testar.
echo Depois compile AutoFarm_Instalador.iss no Inno Setup.
echo ATENCAO: Tesseract OCR e externo, e o Windows pode bloquear EXEs nao assinados.
pause
exit /b 0

:error
echo.
echo ERRO: nao foi possivel compilar. Leia as mensagens acima.
pause
exit /b 1
