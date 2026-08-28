@echo off
setlocal
cd /d "%~dp0"
title "MCMA - Configuration Pare-feu Reseau Local"
color 0E

echo ======================================================================
echo    MCMA Sinistres - Autorisation du Port 8000 sur le Reseau Local
echo ======================================================================
echo.
echo Ce script configure le Pare-feu Windows Defender pour autoriser
echo les autres ordinateurs de l'agence a acceder au Tableau de Bord.
echo.

:: Open port 8000 in Windows Firewall
netsh advfirewall firewall show rule name="MCMA Dashboard (Port 8000)" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] La regle de pare-feu existe deja pour le port 8000.
) else (
    echo [*] Ajout de la regle pare-feu pour le port 8000...
    netsh advfirewall firewall add rule name="MCMA Dashboard (Port 8000)" dir=in action=allow protocol=TCP localport=8000 profile=any
    if %errorlevel% equ 0 (
        echo [OK] Port 8000 autorise avec succes !
    ) else (
        echo [!] Veuillez executer ce script en tant qu'Administrateur (Clic-droit - Executer en tant qu'administrateur).
    )
)

echo.
echo ======================================================================
echo  Configuration terminee. Vous pouvez maintenant lancer l'application !
echo ======================================================================
echo.
pause
