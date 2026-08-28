@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title "MCMA Sinistres - Lanceur Tout-en-Un"
color 0B

echo ======================================================================
echo    ==============================================================
echo       MCMA SINISTRES - CENTRE DE NOTIFICATIONS ET AUTOMATISATION
echo    ==============================================================
echo ======================================================================
echo.

:: 1. Verifier Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [X] Erreur : Python n'est pas installe sur cet ordinateur.
    echo     Veuillez installer Python (cochez 'Add to PATH' lors de l'installation).
    echo.
    pause
    exit /b
)

:: 2. Autoriser automatiquement le Pare-feu pour l'acces reseau
netsh advfirewall firewall show rule name="MCMA Dashboard (Port 8000)" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="MCMA Dashboard (Port 8000)" dir=in action=allow protocol=TCP localport=8000 profile=any >nul 2>&1
)

:: 3. Verifier si la session MCMA existe, sinon lancer la connexion
if not exist "mcma_auth_state.json" (
    color 0E
    echo [*] PREMIERE CONNEXION REQUISE :
    echo     Une fenetre de navigateur va s'ouvrir sur MCMA.
    echo     1. Saisissez votre Identifiant et Mot de passe.
    echo     2. Saisissez le code SMS recu sur votre telephone.
    echo.
    python auth_setup.py
    echo.
    if not exist "mcma_auth_state.json" (
        color 0C
        echo [X] La connexion n'a pas pu etre finalisee. Veuillez relancer ce fichier.
        echo.
        pause
        exit /b
    )
)

:: 4. Recuperer automatiquement les dernieres notifications en arriere-plan
color 0B
echo [*] Extraction automatique des notifications et alertes MCMA en cours...
python get_notifications.py --headless

:: 5. Detecter l'adresse IP locale de l'agence
set LOCAL_IP=
for /f "tokens=4" %%a in ('route print ^| find " 0.0.0.0 "') do (
    set LOCAL_IP=%%a
    goto :ip_found
)
:ip_found

echo.
echo ======================================================================
echo  [OK] APPLICATION PRETE ET ACTIVE !
echo ======================================================================
echo.
echo  LIENS DU TABLEAU DE BORD :
echo    - Sur ce PC             : http://localhost:8000
if defined LOCAL_IP (
echo    - Pour vos collegues    : http://%LOCAL_IP%:8000
)
echo.
echo ======================================================================
echo  (Gardez cette fenetre ouverte pour que le serveur reste actif)
echo ======================================================================
echo.

:: 6. Ouvrir automatiquement le navigateur sur le tableau de bord
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: 7. Lancer le serveur principal
python main.py

pause
