@echo off
setlocal
cd /d "%~dp0"
title "MCMA - Centre de Notifications et Suivi des Actions (local)"
color 0B

echo ======================================================================
echo    MCMA Sinistres - Tableau de Bord des Notifications (local)
echo ======================================================================
echo.

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Erreur : Python n'est pas installe ou non detecte dans le PATH.
    echo.
    pause
    exit /b
)

echo [*] Acces au Tableau de Bord (sur ce PC uniquement) :
echo     - http://localhost:8000
echo.
echo [*] Demarrage du serveur...
echo.

:: Open browser on this PC after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: Start FastAPI application from the script's folder
python main.py

pause
