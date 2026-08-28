@echo off
title MCMA — Centre de Notifications & Suivi des Actions
color 0B

echo ======================================================================
echo    MCMA Sinistres — Tableau de Bord des Notifications
echo ======================================================================
echo.
echo [*] Demarrage du serveur local...

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Erreur : Python n'est pas installe ou non detecte dans le PATH.
    echo.
    pause
    exit /b
)

:: Open the browser after 2 seconds in the background
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: Start FastAPI application
python main.py

pause
