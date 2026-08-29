@echo off
title MCMA Agent - New PC Setup
color 0A

echo ================================================================
echo       MCMA / MAMDA Dossier Automation - Setup for New PC
echo ================================================================
echo.

:: 1. Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [X] ERROR: Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.10 or higher from https://www.python.org/
    echo IMPORTANT: Make sure to check 'Add python.exe to PATH' during installation!
    echo.
    pause
    exit /b 1
)

echo [*] Python detected:
python --version
echo.

:: 2. Upgrade pip
echo [*] Step 1/3: Upgrading pip...
python -m pip install --upgrade pip --quiet

:: 3. Install Python dependencies from requirements.txt
echo [*] Step 2/3: Installing Python packages (FastAPI, Playwright, PyMuPDF, httpx, etc.)...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    color 0C
    echo [X] ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)
echo [V] Python dependencies installed successfully.
echo.

:: 4. Install Playwright Chromium browser
echo [*] Step 3/3: Installing Playwright Chromium browser...
python -m playwright install chromium
if %errorlevel% neq 0 (
    color 0C
    echo [X] ERROR: Failed to install Chromium browser.
    pause
    exit /b 1
)
echo [V] Chromium browser installed successfully.
echo.

:: 5. Verification
echo ================================================================
echo                   SETUP COMPLETE & READY!
echo ================================================================
echo.
echo Prochaines etapes (voir GUIDE_INSTALLATION_AGENCE.md) :
echo   1. Se_Connecter_MCMA.bat        -- connexion MCMA + code SMS (OTP)
echo   2. Extraire_Notifications_MCMA.bat -- premiere extraction des alertes
echo   3. DEMARRER_MCMA.bat            -- lancer le tableau de bord
echo.
echo NOTE : le module de remplissage automatique des formulaires
echo        (run_dossier.py) est DESACTIVE. Voir core\features.py.
echo.
pause
