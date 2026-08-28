@echo off
cd /d "%~dp0"
title MCMA Sinistres - Lanceur

echo ======================================================================
echo    MCMA SINISTRES - TABLEAU DE BORD ET AUTOMATISATION
echo ======================================================================
echo.

:: Verifier Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python n'est pas installe ou introuvable dans le PATH.
    echo.
    pause
    exit /b
)

echo [*] Ouverture du navigateur sur http://localhost:8000 ...
start "" "http://localhost:8000"

echo [*] Lancement du serveur...
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Le serveur s'est arrete avec une erreur.
)

pause
