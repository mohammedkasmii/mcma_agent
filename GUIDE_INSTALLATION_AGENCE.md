# 📘 Guide d'Installation & d'Exploitation — MCMA Sinistres (Agence)

**Système :** Centre de Notifications & Suivi des Actions MCMA / MAMDA
**Public :** la personne qui installe le système sur le PC serveur de l'agence
**Durée d'installation :** environ 45 minutes
**Dernière mise à jour :** Août 2026

---

## 0. Ce que fait ce système — et ce qu'il ne fait pas encore

Lisez cette section en premier. Elle évite les mauvaises surprises.

### ✅ Ce qui fonctionne aujourd'hui

- Extraction de **toutes les alertes** du portail MCMA/MAMDA (toutes catégories, toutes les lignes).
- **Tableau de bord web** consultable par tous les employés de l'agence depuis leur propre PC ou téléphone.
- **Suivi du travail** : chaque alerte peut être marquée `À Traiter` / `En Cours` / `Traité` / `En Attente`, avec une note libre.
- **Recherche instantanée** par référence, immatriculation, sociétaire, police.
- **Lien direct** vers le dossier concerné sur le portail MCMA.
- **Renouvellement de session** en 1 clic depuis le tableau de bord.

### ⚠️ Ce qui n'est PAS encore en place

| Limite actuelle | Conséquence pratique |
| :--- | :--- |
| **Un seul compte portail à la fois** | Le système gère la session d'**un** compte MCMA/MAMDA. Le multi-comptes (4 profils) est prévu mais non développé. |
| **Pas d'actualisation automatique** | Les alertes ne se rafraîchissent pas toutes seules. Un employé doit cliquer **« Actualiser MCMA »**. |
| **Notes stockées dans un fichier JSON** | Si deux employés modifient un statut **exactement à la même seconde**, une des deux modifications peut être perdue. Rare, mais réel. La base SQLite corrigera ce point. |
| **Module de remplissage automatique DÉSACTIVÉ** | Le remplissage des rapports d'expertise (Mode Normal / Conventionné) est présent dans le code mais **volontairement désactivé**. Il n'agira pas sur le portail. |
| **Session expire** | Il faut se reconnecter (code SMS) régulièrement, en général chaque matin. |

> 👉 Ces limites sont documentées et planifiées dans `PROJECT_ARCHITECTURE_BLUEPRINT.md`. Le système est **utilisable en production dès aujourd'hui** avec ces réserves.

---

## 1. Prérequis

### Matériel — le PC serveur

| Élément | Minimum |
| :--- | :--- |
| Système | Windows 10 ou 11 |
| RAM | 8 Go (4 Go possible mais lent) |
| Disque | 5 Go libres (Python + Chromium) |
| Réseau | **Câble Ethernet** vers le routeur de l'agence (pas de Wi-Fi — l'IP doit être stable) |
| Disponibilité | Allumé pendant toute la journée de travail |

> C'est le PC qui héberge le tableau de bord. C'est aussi le seul PC où la fenêtre de connexion MCMA s'ouvrira. Il doit rester **allumé et la session Windows ouverte**.

### Humain

- Les **identifiants MCMA/MAMDA** de l'agence.
- Le **téléphone qui reçoit les codes SMS (OTP)** — il doit être disponible chaque matin.
- Un compte **administrateur Windows** sur le PC serveur (pour le pare-feu).

### Réseau

- Tous les PC employés doivent être sur le **même réseau local** que le PC serveur.
- Notez le préfixe réseau de l'agence : généralement `192.168.1.x`. Vous le vérifierez à l'étape 3.

---

## 2. Étape 0 — À faire AVANT de partir à l'agence

⚠️ **Sur votre PC de développement, pas à l'agence.**

### 2.1 Ne rendez JAMAIS le dépôt GitHub public

Le fichier `static/app.js` contient encore des **données réelles** (noms de sociétaires, immatriculations, numéros de police) codées en dur comme jeu de démonstration. Elles sont aussi présentes dans **l'historique Git**.

Rendre le dépôt public — même après avoir supprimé ces données — les exposerait publiquement.

**Le transfert du code se fait hors ligne (étape 1). Le dépôt reste privé.**

Si vous voulez malgré tout nettoyer avant transfert :

```powershell
# Remplacez le bloc SAMPLE_NOTIFICATIONS de static/app.js par des données fictives
# (style : ALAOUI Mohamed / 12345-A-7 / DTA-2024-098765)
```

### 2.2 Vérifiez que tout passe

```powershell
cd C:\Users\hp\Desktop\mcma_agent
python -m pytest -q
```

Résultat attendu : `32 passed`.

### 2.3 Préparez le paquet de transfert

Voir l'étape 1 ci-dessous — choisissez votre méthode et créez le fichier **avant** de vous déplacer.

---

## 3. Étape 1 — Transférer le code à l'agence

Choisissez **une** des trois méthodes. Toutes gardent le dépôt privé.

### Méthode A — Clé USB avec l'historique Git (recommandée)

Sur votre PC :

```powershell
cd C:\Users\hp\Desktop\mcma_agent
git bundle create D:\mcma.bundle --all
```

Sur le PC de l'agence (clé USB insérée) :

```powershell
cd C:\
git clone D:\mcma.bundle mcma_agent
cd mcma_agent
git checkout feat/disable-form-filling-agent
```

> Nécessite Git installé sur le PC agence. Avantage : historique complet, mises à jour futures faciles.

### Méthode B — Clé USB, simple copie (la plus simple)

1. Copiez tout le dossier `mcma_agent` sur la clé USB.
2. **Supprimez** de la copie : `.venv\`, `__pycache__\`, `.pytest_cache\`, `logs\`, `mcma_auth_state.json`.
3. Collez dans `C:\mcma_agent` sur le PC de l'agence.

> Pas besoin de Git. Inconvénient : les mises à jour futures se font par recopie manuelle.

### Méthode C — Accès GitHub privé

Ajoutez le compte GitHub de l'agence comme **collaborateur** sur le dépôt privé, puis :

```powershell
cd C:\
git clone https://github.com/mohammedkasmii/mcma_agent.git
cd mcma_agent
git checkout feat/disable-form-filling-agent
```

> ✅ **Emplacement recommandé : `C:\mcma_agent`** — chemin court, sans espaces, sans accents. Évitez le Bureau ou `Mes Documents`.

---

## 4. Étape 2 — Installer Python et les dépendances

### 4.1 Installer Python

1. Téléchargez Python 3.10 ou supérieur : <https://www.python.org/downloads/>
2. Lancez l'installateur.
3. ⚠️ **COCHEZ LA CASE `Add python.exe to PATH`** en bas de la première fenêtre. C'est l'erreur n°1.
4. Cliquez sur *Install Now*.

Vérification — ouvrez une **nouvelle** fenêtre PowerShell :

```powershell
python --version
```

Doit afficher `Python 3.10.x` ou supérieur. Si vous obtenez une erreur, Python n'est pas dans le PATH : réinstallez en cochant la case.

### 4.2 Installer les dépendances

Double-cliquez sur **`setup_new_pc.bat`**.

Ou en ligne de commande :

```powershell
cd C:\mcma_agent
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

> ⏱️ Comptez 5 à 10 minutes. Le téléchargement de Chromium fait environ 150 Mo.

Vérification :

```powershell
cd C:\mcma_agent
python -m pytest -q
```

Résultat attendu : `32 passed`.

---

## 5. Étape 3 — Fixer l'adresse IP du serveur

**Pourquoi :** les raccourcis des employés pointent vers une adresse IP. Si le routeur change cette adresse (DHCP), tous les raccourcis cassent du jour au lendemain.

### 5.1 Relever l'adresse actuelle

```powershell
ipconfig
```

Repérez la carte Ethernet et notez :

```
Adresse IPv4. . . . . . . . . . . . . .: 192.168.1.17     <- l'IP du serveur
Masque de sous-réseau. . . . . . . . . : 255.255.255.0
Passerelle par défaut. . . . . . . . . : 192.168.1.1      <- le routeur
```

### 5.2 Rendre l'adresse fixe

**Interface graphique :** Paramètres → Réseau et Internet → Ethernet → Attribution IP → *Modifier* → **Manuel** → activer IPv4 :

| Champ | Valeur |
| :--- | :--- |
| Adresse IP | `192.168.1.17` *(hors de la plage DHCP du routeur si possible)* |
| Masque | `255.255.255.0` |
| Passerelle | `192.168.1.1` |
| DNS préféré | `192.168.1.1` (ou `8.8.8.8`) |

**Ou en PowerShell administrateur :**

```powershell
netsh interface ip set address name="Ethernet" static 192.168.1.17 255.255.255.0 192.168.1.1
```

> 📝 **Notez cette adresse.** Elle sera utilisée partout ensuite. Dans ce guide nous l'appelons `192.168.1.17` — remplacez-la par la vôtre.

---

## 6. Étape 4 — Ouvrir le pare-feu (port 8000)

Ouvrez PowerShell **en tant qu'administrateur** (clic droit → *Exécuter en tant qu'administrateur*) :

```powershell
netsh advfirewall firewall add rule name="MCMA Dashboard (Port 8000)" dir=in action=allow protocol=TCP localport=8000 profile=private remoteip=192.168.1.0/24
```

> ⚠️ **N'utilisez pas `Autoriser_Reseau_Local.bat` tel quel.** Ce script ouvre le port à `profile=any`, ce qui inclut le **Wi-Fi invité**. La commande ci-dessus le restreint au réseau privé de l'agence uniquement. Adaptez `192.168.1.0/24` si votre réseau utilise un autre préfixe.

Vérification :

```powershell
netsh advfirewall firewall show rule name="MCMA Dashboard (Port 8000)"
```

---

## 7. Étape 5 — Première connexion MCMA (code SMS)

📱 **Ayez le téléphone qui reçoit les SMS à portée de main.**

Double-cliquez sur **`Se_Connecter_MCMA.bat`**.

Ou :

```powershell
cd C:\mcma_agent
python auth_setup.py
```

Ce qui se passe :

1. Une fenêtre Chromium s'ouvre sur la page de connexion MCMA.
2. Saisissez **identifiant** et **mot de passe**.
3. Saisissez le **code SMS (OTP)** reçu.
4. Dès que le tableau de bord MCMA s'affiche, le script détecte la connexion et enregistre la session dans `mcma_auth_state.json`.
5. La fenêtre se ferme automatiquement.

Message attendu :

```
[✓] SUCCESS! Verified session saved to 'mcma_auth_state.json'
```

Vérification à tout moment :

```powershell
python session_keeper.py --check
```

> 🔒 Le fichier `mcma_auth_state.json` contient vos cookies de session. Il est exclu de Git et **ne doit jamais être partagé ni copié** sur un autre poste.

---

## 8. Étape 6 — Première extraction des alertes

Double-cliquez sur **`Extraire_Notifications_MCMA.bat`**.

Ou :

```powershell
cd C:\mcma_agent
python get_notifications.py --headless
```

Résultat attendu :

```
======================================================================
  ✅ Extraction Complete!
  📊 Total Categories : 2
  📝 Total Alerts     : 12
  📁 Output Saved To  : logs\mcma_notifications.json
======================================================================
```

> Si vous obtenez *« MCMA session expired »*, retournez à l'étape 5.

---

## 9. Étape 7 — Démarrer le tableau de bord

Double-cliquez sur **`DEMARRER_MCMA.bat`**.

Ou :

```powershell
cd C:\mcma_agent
python main.py
```

Affichage attendu :

```
======================================================================
  🔔  MCMA SINISTRES — CENTRE DE NOTIFICATIONS & ACTIONS
======================================================================
  💻  Accès sur ce PC          : http://localhost:8000
  👥  Accès pour vos collègues : http://192.168.1.17:8000
======================================================================
  👉  Gardez cette fenêtre ouverte pour que le serveur reste actif.
```

⚠️ **Cette fenêtre noire doit rester ouverte.** Si quelqu'un la ferme, le tableau de bord devient inaccessible pour toute l'agence. L'étape 9 automatise le démarrage pour éviter ce risque.

> 💡 Le script ouvre le navigateur *avant* que le serveur ne soit prêt. Si la page affiche une erreur au premier chargement, patientez 3 secondes et actualisez (F5).

**Test depuis un autre PC de l'agence :** ouvrez `http://192.168.1.17:8000`. Le tableau de bord doit s'afficher.

---

## 10. Étape 8 — Donner l'accès aux employés

### 10.1 Corriger les raccourcis (obligatoire)

Deux fichiers contiennent une adresse IP codée en dur — celle du PC de développement. **Il faut les modifier** avec l'IP réelle de votre serveur.

**`Ouvrir_MCMA_Employe.bat`** — remplacez la ligne :

```bat
start http://192.168.1.17:8000
```

**`MCMA_Dashboard_Employe.url`** — remplacez la ligne :

```
URL=http://192.168.1.17:8000
```

Ouvrez-les avec le Bloc-notes, corrigez l'adresse, enregistrez.

### 10.2 Distribuer

Copiez **`MCMA_Dashboard_Employe.url`** sur le Bureau de chaque employé. Un double-clic ouvre le tableau de bord.

Sur téléphone ou tablette : ouvrir `http://192.168.1.17:8000` dans le navigateur et *Ajouter à l'écran d'accueil*.

### 10.3 Prise en main — les 5 boutons

| Élément | Rôle |
| :--- | :--- |
| **Pastille de statut** (⚪ À Traiter) | Cliquez dessus pour faire défiler : À Traiter → En Cours → Traité → En Attente |
| **Bouton Note** ✏️ | Ajoute un commentaire libre et permet de choisir le statut |
| **Champ de recherche** | Filtre instantanément par référence, immatriculation, sociétaire, police |
| **« Actualiser MCMA »** | Récupère les alertes en direct depuis le portail |
| **« Reconnecter »** | Ouvre la fenêtre de connexion **sur le PC serveur** (pour le code SMS) |
| **« Ouvrir »** (par ligne) | Ouvre le dossier correspondant directement sur le portail MCMA |

> ⚠️ **« Actualiser MCMA » lance un navigateur invisible sur le serveur.** Ne cliquez pas à cinq en même temps : chaque clic ouvre un Chromium supplémentaire et ralentit le PC. **Convention : une seule personne actualise, les autres attendent quelques secondes.**

---

## 11. Étape 9 — Démarrage automatique (fortement recommandé)

Objectif : plus personne n'a besoin de penser à lancer le serveur, et il redémarre tout seul.

### 11.1 Préparer une session Windows toujours ouverte

Le système a besoin d'une **session Windows ouverte** (pas d'un service Windows), car la fenêtre de connexion MCMA doit pouvoir s'afficher à l'écran.

- Créez ou utilisez un compte Windows dédié, ex. `AgenceMCMA`.
- Configurez l'ouverture de session automatique au démarrage.
- Désactivez la mise en veille : Paramètres → Système → Alimentation → *Ne jamais* mettre en veille.
- Désactivez le verrouillage automatique de l'écran.

### 11.2 Créer la tâche planifiée

Ouvrez le **Planificateur de tâches** (`taskschd.msc`) → *Créer une tâche…*

| Onglet | Réglage |
| :--- | :--- |
| **Général** | Nom : `MCMA Dashboard` — cocher **« N'exécuter que si l'utilisateur est connecté »** |
| **Déclencheurs** | Nouveau → **À l'ouverture de session** → utilisateur `AgenceMCMA` |
| **Actions** | Nouveau → Démarrer un programme → Programme : `python` — Arguments : `main.py` — **Commencer dans : `C:\mcma_agent`** |
| **Conditions** | Décocher *« Démarrer seulement si l'ordinateur est sur secteur »* |
| **Paramètres** | Cocher **« En cas d'échec, redémarrer toutes les »** → `1 minute`, jusqu'à `3` tentatives |

> ⚠️ Ne cochez **pas** *« Exécuter même si l'utilisateur n'est pas connecté »*. Cela place la tâche en Session 0, où la fenêtre de connexion MCMA devient invisible — vous ne pourriez plus saisir le code SMS.

Le champ **« Commencer dans »** est obligatoire. Sans lui, Python ne trouvera pas les fichiers du projet.

### 11.3 Tester

Redémarrez le PC. Après l'ouverture de session automatique, `http://192.168.1.17:8000` doit répondre sans aucune intervention.

---

## 12. Étape 10 — Sauvegarde

Les notes et statuts des employés vivent dans **`logs\notification_actions.json`**. C'est le seul fichier réellement irremplaçable.

Créez `C:\mcma_agent\sauvegarde.bat` :

```bat
@echo off
cd /d "%~dp0"
set D=%date:~-4%%date:~3,2%%date:~0,2%
if not exist "backups" mkdir "backups"
copy /Y "logs\notification_actions.json" "backups\notification_actions_%D%.json"
echo Sauvegarde effectuee : backups\notification_actions_%D%.json
```

Planifiez-le dans le Planificateur de tâches, **tous les jours à 18h15**, et copiez régulièrement le dossier `backups\` sur un second PC ou un NAS.

> Une clé USB laissée branchée en permanence est la solution la moins fiable — à éviter si possible.

---

## 13. Routine quotidienne

### Le matin (~08h00) — 2 minutes

1. Vérifier que le tableau de bord répond : `http://192.168.1.17:8000`.
2. Cliquer sur **« Actualiser MCMA »**.
3. Si un message d'erreur ou de session expirée apparaît :
   - Cliquer sur **« Reconnecter »** (ou lancer `Se_Connecter_MCMA.bat` sur le serveur),
   - saisir identifiant, mot de passe et **code SMS**,
   - cliquer de nouveau sur **« Actualiser MCMA »**.

📱 **Le téléphone qui reçoit les SMS doit être présent le matin.** Le portail MCMA n'accepte plus de connexion après 18h00 : une session perdue en fin de journée ne pourra être rétablie que le lendemain matin.

### Pendant la journée

- Les employés traitent les alertes et mettent à jour statuts et notes.
- Actualiser toutes les 30 à 60 minutes, **par une seule personne à la fois**.

### Le soir (18h00)

- Rien à faire. Laisser le PC allumé et la session ouverte.

---

## 14. Dépannage

| Symptôme | Cause probable | Solution |
| :--- | :--- | :--- |
| `python n'est pas reconnu` | PATH non configuré | Réinstaller Python en cochant *Add python.exe to PATH*, puis rouvrir PowerShell |
| Les collègues ne peuvent pas ouvrir la page | Pare-feu ou mauvaise IP | Refaire l'étape 4 en administrateur ; vérifier l'IP avec `ipconfig` |
| La page s'ouvre sur le serveur mais pas ailleurs | Règle pare-feu absente ou mauvais sous-réseau | Vérifier `remoteip=192.168.1.0/24` correspond bien à votre réseau |
| `MCMA session expired` | Session expirée | `Se_Connecter_MCMA.bat` (code SMS requis) |
| « Actualiser » ne renvoie rien | Session expirée, ou portail fermé (après 18h) | Reconnexion ; après 18h, attendre le lendemain |
| Le PC devient très lent | Plusieurs actualisations simultanées | Attendre ; une seule personne actualise à la fois |
| Tableau de bord inaccessible d'un coup | Fenêtre noire fermée, ou PC redémarré | Relancer `DEMARRER_MCMA.bat` ; mettre en place l'étape 9 |
| Les raccourcis employés ne marchent plus | L'IP du serveur a changé | Fixer l'IP (étape 5), corriger les raccourcis (étape 10.1) |
| `Erreur de lecture du fichier JSON` | Cache d'alertes corrompu | Supprimer `logs\mcma_notifications.json` et réextraire |
| Page blanche / erreur au démarrage | Navigateur ouvert avant le serveur | Attendre 3 secondes et actualiser (F5) |

### Commandes de diagnostic

```powershell
cd C:\mcma_agent

python session_keeper.py --check     # état de la session MCMA
python -m pytest -q                  # intégrité du code (attendu : 32 passed)
ipconfig                             # adresse IP du serveur
curl http://localhost:8000/health    # le serveur répond-il ?
```

`/health` doit renvoyer :

```json
{"status":"ok","service":"mcma-automation-agent","version":"2.0.0","features":{"form_filling":false}}
```

`"form_filling": false` confirme que le module de remplissage automatique est bien désactivé.

---

## 15. Le module de remplissage automatique (désactivé)

Le code du remplissage automatique des rapports d'expertise est présent mais **inerte**. Aucune action ne sera effectuée sur le portail.

| Point d'entrée | Comportement actuel |
| :--- | :--- |
| `POST /api/v1/fill-dossier` | Refus HTTP 503 |
| `POST /api/v1/fill-dossier-from-wexia` | Refus HTTP 503 |
| `python run_dossier.py` | Refuse et quitte |
| `menu.py` option 1 | Marquée `[DESACTIVE]` |

**Ne tentez pas de l'activer à l'agence.** Sa réactivation exige des travaux préalables décrits dans `PROJECT_ARCHITECTURE_BLUEPRINT.md` §11 : politique de sécurité à deux niveaux, vérification de l'écriture qui échoue en cas de doute, et rapport de contrôle avant validation humaine.

---

## 16. Fiche de référence rapide

📌 *À imprimer et coller près du PC serveur.*

```
╔══════════════════════════════════════════════════════════════════╗
║  MCMA SINISTRES — AIDE-MÉMOIRE                                   ║
╠══════════════════════════════════════════════════════════════════╣
║  Adresse du tableau de bord                                      ║
║      http://192.168.1.17:8000        <-- À CORRIGER              ║
║                                                                  ║
║  Dossier du projet : C:\mcma_agent                               ║
╠══════════════════════════════════════════════════════════════════╣
║  CHAQUE MATIN                                                    ║
║   1. Ouvrir le tableau de bord                                   ║
║   2. Cliquer « Actualiser MCMA »                                 ║
║   3. Si erreur -> « Reconnecter » + code SMS                     ║
╠══════════════════════════════════════════════════════════════════╣
║  FICHIERS À DOUBLE-CLIC (sur le PC serveur)                      ║
║   Se_Connecter_MCMA.bat ......... connexion + code SMS           ║
║   Extraire_Notifications_MCMA.bat  extraction des alertes        ║
║   DEMARRER_MCMA.bat ............. démarrer le serveur            ║
╠══════════════════════════════════════════════════════════════════╣
║  RÈGLES IMPORTANTES                                              ║
║   • Ne pas fermer la fenêtre noire du serveur                    ║
║   • Une seule personne actualise à la fois                       ║
║   • Téléphone SMS disponible le matin                            ║
║   • Portail MCMA fermé après 18h00                               ║
╠══════════════════════════════════════════════════════════════════╣
║  EN CAS DE BLOCAGE                                               ║
║   cd C:\mcma_agent                                               ║
║   python session_keeper.py --check                               ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 17. Checklist d'installation

Cochez au fur et à mesure :

- [ ] Python 3.10+ installé, `Add to PATH` coché
- [ ] Code copié dans `C:\mcma_agent`
- [ ] `setup_new_pc.bat` exécuté sans erreur
- [ ] `python -m pytest -q` → `32 passed`
- [ ] Adresse IP du serveur fixée : `______________________`
- [ ] Règle pare-feu créée avec `remoteip=` du sous-réseau de l'agence
- [ ] Première connexion MCMA réussie (`mcma_auth_state.json` créé)
- [ ] Première extraction réussie (`logs\mcma_notifications.json` créé)
- [ ] Tableau de bord accessible depuis le PC serveur
- [ ] Tableau de bord accessible depuis **un autre PC** de l'agence
- [ ] `Ouvrir_MCMA_Employe.bat` et `MCMA_Dashboard_Employe.url` corrigés avec la bonne IP
- [ ] Raccourci distribué sur le Bureau de chaque employé
- [ ] Ouverture de session Windows automatique configurée
- [ ] Tâche planifiée `MCMA Dashboard` créée et testée après redémarrage
- [ ] Mise en veille et verrouillage automatique désactivés
- [ ] Sauvegarde quotidienne planifiée à 18h15
- [ ] Employés formés aux 5 boutons (§10.3)
- [ ] Aide-mémoire (§16) imprimé et affiché

---

## 18. Contacts & documents

| Document | Contenu |
| :--- | :--- |
| `PROJECT_ARCHITECTURE_BLUEPRINT.md` | Architecture cible, décisions, feuille de route |
| `NOTIFICATIONS_SETUP_GUIDE.md` | Guide rapide développeur |
| `README.md` | Vue d'ensemble et état des modules |
| `GARAGE_CONVENTIONNE_ANALYSIS.md` | Analyse technique du portail (Phase 2) |

**Dépôt Git :** `https://github.com/mohammedkasmii/mcma_agent` — **privé, à garder privé** (§2.1).
**Branche déployée :** `feat/disable-form-filling-agent`
