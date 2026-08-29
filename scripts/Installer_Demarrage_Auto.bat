@echo off
setlocal
cd /d "%~dp0.."
title "MCMA - Installation du demarrage automatique"
color 0B

echo ======================================================================
echo    MCMA Sinistres - Demarrage automatique a l'ouverture de session
echo ======================================================================
echo.
echo Cette tache demarre le serveur MCMA automatiquement des l'ouverture
echo de session Windows, et le relance en cas d'arret imprevu.
echo.
echo IMPORTANT : la tache s'execute UNIQUEMENT quand la session est
echo ouverte. C'est volontaire : la fenetre de connexion MCMA (code SMS)
echo doit pouvoir s'afficher a l'ecran, ce qui est impossible pour un
echo service Windows (isolation Session 0).
echo.

schtasks /Query /TN "MCMA Dashboard" >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Tache existante detectee - suppression avant recreation...
    schtasks /Delete /TN "MCMA Dashboard" /F >nul 2>&1
)

echo [*] Creation de la tache planifiee...
schtasks /Create ^
    /TN "MCMA Dashboard" ^
    /TR "cmd /c cd /d \"%~dp0\" && python main.py" ^
    /SC ONLOGON ^
    /RL LIMITED ^
    /F

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [X] Echec. Relancez ce script en tant qu'administrateur.
    pause
    exit /b 1
)

echo.
echo [OK] Tache "MCMA Dashboard" creee.
echo.
echo ETAPE MANUELLE RESTANTE (redemarrage automatique en cas de panne) :
echo   1. Ouvrez le Planificateur de taches (taskschd.msc)
echo   2. Trouvez "MCMA Dashboard" - clic droit - Proprietes
echo   3. Onglet "Parametres" :
echo        [x] En cas d'echec, redemarrer toutes les : 1 minute
echo            Nombre de tentatives : 3
echo   4. Onglet "Conditions" :
echo        [ ] Decochez "Demarrer seulement si l'ordinateur est sur secteur"
echo.
echo A VERIFIER AUSSI :
echo   - Ouverture de session Windows automatique activee
echo   - Mise en veille desactivee (Parametres - Systeme - Alimentation)
echo   - Verrouillage automatique de l'ecran desactive
echo.
echo ======================================================================
pause
