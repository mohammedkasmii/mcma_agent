@echo off
title MCMA — Centre de Notifications & Suivi des Actions
color 0B

echo ======================================================================
echo    MCMA Sinistres — Tableau de Bord des Notifications
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

:: Find local IP address
for /f "tokens=4" %%a in ('route print ^| find " 0.0.0.0 "') do (
    set LOCAL_IP=%%a
    goto :ip_found
)
:ip_found

echo [*] Liens d'acces au Tableau de Bord :
echo     - Sur ce PC             : http://localhost:8000
if defined LOCAL_IP (
echo     - Pour vos collegues    : http://%LOCAL_IP%:8000
)
echo.
echo [*] Demarrage du serveur...
echo.

:: Open browser on this PC after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: Start FastAPI application
python main.py

pause
