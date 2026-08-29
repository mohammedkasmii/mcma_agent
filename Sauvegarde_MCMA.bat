@echo off
setlocal
cd /d "%~dp0"
title "MCMA - Sauvegarde de la base de donnees"

if not exist "backups" mkdir "backups"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set LDT=%%I
set STAMP=%LDT:~0,8%

echo [*] Sauvegarde de data\mcma.db ...
python -c "import sqlite3,os,sys; d=r'backups\mcma-%STAMP%.db'; c=sqlite3.connect(r'data\mcma.db'); c.execute('VACUUM INTO ?',(d,)); c.close(); print('[OK] ' + d)" 2>nul

if %errorlevel% neq 0 (
    echo [!] VACUUM INTO indisponible - copie simple a la place.
    copy /Y "data\mcma.db" "backups\mcma-%STAMP%.db" >nul
    echo [OK] backups\mcma-%STAMP%.db
)

echo [*] Purge des sauvegardes de plus de 14 jours...
forfiles /P "backups" /M "mcma-*.db" /D -14 /C "cmd /c del @path" 2>nul

echo.
echo Pensez a copier le dossier backups\ sur un second PC ou un NAS.
