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
echo [2/2] Compilando agente...
pyinstaller agent.spec --clean --noconfirm
if errorlevel 1 (
    echo ERRO na compilacao.
    pause & exit /b 1
)

echo.
echo ================================================
echo  Concluido!
echo  Executavel gerado em: dist\agent.exe
echo  Copie tambem o config.ini para a mesma pasta.
echo ================================================
pause
