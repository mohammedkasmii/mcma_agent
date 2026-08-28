# 🔔 Guide de Démarrage Rapide — Module Notifications & Dashboard MCMA

Ce guide vous permet d'installer, de tester et de visualiser le système de **Notifications et Alertes MCMA** sur un nouveau PC en quelques minutes.

---

## 🚀 Étape 1 : Récupérer le Projet (Git)

Ouvrez un terminal **PowerShell** :

```powershell
# Si vous clonez pour la première fois :
git clone https://github.com/mohammedkasmii/mcma_agent.git
cd mcma_agent
git checkout refactor/solid-architecture

# Si vous avez déjà le dossier :
git fetch origin
git checkout refactor/solid-architecture
git pull origin refactor/solid-architecture
```

---

## 📦 Étape 2 : Installer les Dépendances

```powershell
# 1. Installer les packages Python requis
pip install -r requirements.txt

# 2. Installer le navigateur Chromium pour Playwright
playwright install chromium
```

---

## 🔑 Étape 3 : Authentification Initiale MCMA (Login + OTP)

```powershell
python auth_setup.py
```

1. Une fenêtre de navigateur s'ouvre automatiquement sur la page de connexion MCMA.
2. Saisissez votre **Nom d'utilisateur** et **Mot de passe**.
3. Saisissez le code **SMS / OTP** reçu sur votre téléphone.
4. Dès que le tableau de bord MCMA apparaît, le script sauvegarde automatiquement la session dans `mcma_auth_state.json`.

---

## 🔔 Étape 4 : Extraire les Notifications & Tableaux en Direct

Lancez l'extracteur de notifications :

```powershell
python get_notifications.py
```

*(Ou en arrière-plan sans ouvrir de fenêtre : `python get_notifications.py --headless`)*

**Résultats :**
- Récupère toutes les catégories d'alertes du menu supérieur (`#listeAlertes`).
- Extrait toutes les lignes du tableau : **Référence, Date de survenance, Nom du sociétaire, N° Police, Immatriculation, Nature, Statut et Lien direct**.
- Enregistre les données au format JSON dans `logs/mcma_notifications.json`.

---

## 🌐 Étape 5 : Lancer le Tableau de Bord Web

Démarrez le serveur local :

```powershell
python main.py
```

Puis ouvrez votre navigateur à l'adresse :
👉 **[http://localhost:8000](http://localhost:8000)**

### 💡 Fonctionnalités du Tableau de Bord :
- **📊 Compteurs KPI** : Nombre total d'alertes, factures reçues, catégories actives.
- **📑 Onglets par Catégorie** : Filtrer par `MISSIONS (FACTURES REÇUES)`, `RELANCES`, etc.
- **🔍 Recherche en Temps Réel** : Filtrer instantanément par immatriculation (`WW...`, `...-A-50`), référence, sociétaire ou police.
- **🔗 Bouton "Ouvrir"** : Ouvre directement le dossier de sinistre concerné dans MCMA.
- **🔄 Bouton "Actualiser MCMA"** : Re-synchronise les alertes en direct depuis MCMA en un clic.

---

## ⏱️ Étape 6 (Optionnel) : Maintenir la Session Active 24/7

Pour éviter les déconnexions et les expirations d'OTP pendant la journée, laissez ce script tourner dans un terminal séparé :

```powershell
python session_keeper.py
```

---

## 🧪 Vérification des Tests Unitaires

Pour vérifier que l'ensemble du projet fonctionne correctement :

```powershell
python -m pytest -v
```
*(19/19 tests doivent être affichés en vert `PASSED`).*
