@echo off
setlocal
cd /d "%~dp0"
title "MCMA - Acces reseau local supprime (INC-00)"
color 0E

echo ======================================================================
echo    MCMA Sinistres - Acces Reseau Local SUPPRIME (confinement INC-00)
echo ======================================================================
echo.
echo Ce script n'ouvre plus aucun port et n'ajoute plus aucune regle de
echo pare-feu. L'exposition du tableau de bord sur le reseau local a ete
echo definitivement supprimee pendant la reconstruction : le serveur
echo n'ecoute plus que sur http://localhost:8000 (127.0.0.1).
echo.
echo Pour SUPPRIMER l'ancienne regle de pare-feu de cette machine, un
echo administrateur doit suivre le runbook :
echo.
echo     deploy\decommission_firewall.md
echo.
echo ======================================================================
echo.
pause
