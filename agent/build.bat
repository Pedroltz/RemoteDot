@echo off
echo ================================================
echo  Build - Monitor Agent
echo ================================================

echo.
echo [1/2] Instalando dependencias de build...
pip install pyinstaller pyinstaller-hooks-contrib --quiet
if errorlevel 1 (
    echo ERRO ao instalar PyInstaller.
    pause & exit /b 1
)

echo.
echo [2/3] Compilando agente...
pyinstaller agent.spec --clean --noconfirm
if errorlevel 1 (
    echo ERRO na compilacao do agente.
    pause & exit /b 1
)

echo.
echo [3/3] Compilando desinstalador...
pyinstaller uninstall.spec --clean --noconfirm
if errorlevel 1 (
    echo ERRO na compilacao do desinstalador.
    pause & exit /b 1
)

echo.
echo ================================================
echo  Concluido!
echo  dist\agent.exe     - agente principal
echo  dist\uninstall.exe - remove persistencia
echo  Copie tambem o config.ini para a mesma pasta.
echo ================================================
pause
