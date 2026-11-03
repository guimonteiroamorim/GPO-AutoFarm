@echo off
setlocal
cd /d "%~dp0"
title Compilar GPO_AutoFarm_v11 (ambiente isolado)
set "TESSERACT_DIR=%~dp0tesseract"

echo ==========================================
echo  Compilacao limpa - GPO_AutoFarm_v11
echo ==========================================
echo.

if not exist "%TESSERACT_DIR%\tesseract.exe" goto missing_tesseract
if not exist "%TESSERACT_DIR%\tessdata\eng.traineddata" goto missing_tesseract

echo [0/4] Validando Tesseract portatil e idioma eng...
setlocal
set "PATH=%SystemRoot%\System32;%SystemRoot%"
"%TESSERACT_DIR%\tesseract.exe" --version
if errorlevel 1 goto error
"%TESSERACT_DIR%\tesseract.exe" --list-langs --tessdata-dir "%TESSERACT_DIR%\tessdata" | findstr /x /c:"eng" >nul
if errorlevel 1 goto missing_tesseract
endlocal

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

echo Copiando Tesseract portatil para a distribuicao...
robocopy "%TESSERACT_DIR%" "%~dp0dist\GPO_AutoFarm_v11\tesseract" /E /COPY:DAT /R:2 /W:1
if errorlevel 8 goto error
if not exist "%~dp0dist\GPO_AutoFarm_v11\tesseract\tesseract.exe" goto error
if not exist "%~dp0dist\GPO_AutoFarm_v11\tesseract\tessdata\eng.traineddata" goto error
if not exist "%~dp0dist\GPO_AutoFarm_v11\tesseract\NOTICE.txt" goto error

echo.
echo SUCESSO! Abra dist\GPO_AutoFarm_v11\GPO_AutoFarm_v11.exe para testar.
echo Depois compile AutoFarm_Instalador.iss no Inno Setup.
echo Tesseract OCR e os dados de idioma estao incluidos na pasta tesseract.
echo Nao desative a seguranca do Windows para executar o aplicativo.
pause
exit /b 0

:missing_tesseract
echo.
echo ERRO: runtime portatil incompleto. Obtenha a distribuicao x64 oficial do Tesseract 5.4.0.20240606
echo e confira tesseract\tesseract.exe, as DLLs listadas em tesseract\NOTICE.txt e tessdata\eng.traineddata.
echo Origem oficial: https://github.com/UB-Mannheim/tesseract/releases/tag/v5.4.0.20240606
pause
exit /b 1

:error
echo.
echo ERRO: nao foi possivel compilar. Leia as mensagens acima.
pause
exit /b 1
