@echo off
setlocal
cd /d "%~dp0.."
title "MCMA - Connexion et Authentification OTP"
color 0E

echo ======================================================================
echo    MCMA Sinistres - Connexion & Renouvellement de Session
echo ======================================================================
echo.
echo [*] Une fenetre de navigateur va s'ouvrir...
echo     1. Saisissez votre Identifiant et Mot de passe MCMA.
echo     2. Saisissez le Code SMS (OTP) recu sur votre telephone.
echo     3. Une fois sur le tableau de bord, la session sera enregistree !
echo.
echo ======================================================================
echo.

python -m tools.auth_setup

echo.
echo ======================================================================
echo  Operation terminee. Vous pouvez maintenant fermer cette fenetre.
echo ======================================================================
echo.
pause
