@echo off
setlocal
cd /d "%~dp0.."
title "MCMA - Autorisation reseau local (port 8000)"
color 0E

echo ======================================================================
echo    MCMA Sinistres - Ouverture du port 8000 sur le reseau de l'agence
echo ======================================================================
echo.
echo Ce script autorise UNIQUEMENT le sous-reseau prive de l'agence.
echo Le Wi-Fi invite et les reseaux publics restent bloques.
echo.

set "SUBNET=%~1"
if "%SUBNET%"=="" set "SUBNET=192.168.1.0/24"

echo [*] Sous-reseau autorise : %SUBNET%
echo     (pour un autre reseau : Autoriser_Reseau_Local.bat 192.168.0.0/24)
echo.

netsh advfirewall firewall delete rule name="MCMA Dashboard (Port 8000)" >nul 2>&1

netsh advfirewall firewall add rule ^
    name="MCMA Dashboard (Port 8000)" ^
    dir=in action=allow protocol=TCP localport=8000 ^
    profile=private remoteip=%SUBNET%

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [X] Echec. Relancez ce script en tant qu'administrateur.
    pause
    exit /b 1
)

echo.
echo [OK] Port 8000 autorise pour %SUBNET% (profil prive uniquement).
echo.
pause
