@echo off
title MCMA — Extraction des Notifications
color 0A

echo ======================================================================
echo    MCMA Sinistres — Extraction Rapide des Notifications
echo ======================================================================
echo.
echo [*] Connexion a MCMA et recuperation des alertes en direct...
echo.

python get_notifications.py --headless

echo.
echo ======================================================================
echo  Extraction terminee ! Vous pouvez maintenant ouvrir le Tableau de Bord.
echo ======================================================================
echo.
pause
