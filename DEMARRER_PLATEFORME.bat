@echo off
cd /d "%~dp0"
title MCMA - Plateforme Sinistres
echo ======================================================================
echo    MCMA - Plateforme Sinistres
echo ======================================================================
echo.
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python n'est pas installe ou introuvable dans le PATH.
    echo.
    pause
    exit /b
)
echo [*] Demarrage de la plateforme...
echo [*] Le tableau de bord s'ouvrira sur https://127.0.0.1:8443/
echo.
start "" "https://127.0.0.1:8443/"
python -m mcma.app.main
pause
