# 🧪 Guide de Test — MCMA Sinistres sur Windows

**But :** valider que le projet fonctionne de bout en bout sur un PC Windows,
avant tout déploiement sur le serveur de l'agence.
**Durée :** environ 1 heure (30 min sans accès au portail, 30 min avec).
**Branche testée :** `feat/disable-form-filling-agent`

> Ce guide est un **plan de test**, pas un guide d'installation. Chaque étape
> indique le résultat attendu. Cochez au fur et à mesure et notez ce qui cloche
> dans la fiche de la §8.

---

## 0. Avant de commencer

### 0.1 Ce qu'il vous faut

| | Nécessaire pour |
| :--- | :--- |
| Python 3.10+ avec `Add to PATH` | tout |
| Le code sur la branche `feat/disable-form-filling-agent` | tout |
| **Identifiants MCMA/MAMDA** | Partie 3 uniquement |
| **Téléphone recevant les SMS (OTP)** | Partie 3 uniquement |
| Un 2ᵉ PC sur le même réseau | Partie 4 uniquement |

Les parties 1 et 2 se font **sans aucun accès au portail**. Faites-les d'abord :
si elles échouent, inutile de brûler un code SMS.

### 0.2 ⏰ Le piège n°1 : la fenêtre horaire

Le poller ne tourne **qu'entre 07h45 et 18h00**, du lundi au samedi. C'est voulu
(le portail refuse les connexions après 18h).

**Si vous testez le soir ou le dimanche, rien ne se synchronisera** — et ce n'est
pas un bug. Pour tester hors de ces horaires, forcez la fenêtre :

```powershell
$env:MCMA_WINDOW_START = "00:00"
$env:MCMA_WINDOW_END   = "23:59"
$env:MCMA_WINDOW_DAYS  = "0,1,2,3,4,5,6"
```

> ⚠️ Ces variables ne durent que le temps de la fenêtre PowerShell ouverte.
> Fermez-la et elles disparaissent — ce qui est exactement ce qu'on veut.

### 0.3 Variables d'environnement disponibles

| Variable | Effet | Défaut |
| :--- | :--- | :--- |
| `MCMA_WINDOW_START` / `MCMA_WINDOW_END` | Horaires de synchronisation | `07:45` / `18:00` |
| `MCMA_WINDOW_DAYS` | Jours (0 = lundi … 6 = dimanche) | `0,1,2,3,4,5` |
| `MCMA_POLL_INTERVAL_MINUTES` | Fréquence de synchronisation | `5` |
| `MCMA_DISABLE_POLLER` | `1` = ne pas lancer le poller du tout | non défini |
| `MCMA_ENABLE_FORM_FILLING` | `1` = réactiver le remplissage (⚠️ **ne pas faire**) | non défini |

---

## 1. Installation propre  ⏱️ ~15 min

### ☐ 1.1 Récupérer la bonne branche

```powershell
cd C:\Users\hp\Desktop\mcma_agent
git status
git checkout feat/disable-form-filling-agent
git log --oneline -1
```

**Attendu :** le dernier commit parle de `docs:` ou `chore: reorganise`.

### ☐ 1.2 Repartir d'une base vierge

Pour tester comme si c'était une première installation :

```powershell
Remove-Item -Recurse -Force data -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force sessions -ErrorAction SilentlyContinue
```

> Ne supprime **que** la base de test et les sessions. Ne touche ni au code ni à
> `logs/`.

### ☐ 1.3 Dépendances

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

**Attendu :** aucune erreur. `tzdata` doit faire partie des paquets installés.

### ☐ 1.4 La suite de tests

```powershell
python -m pytest -q
```

**Attendu :**
```
57 passed
```

> ❌ Si ce n'est pas 57, **arrêtez-vous ici** et notez la sortie. Inutile de
> continuer : quelque chose ne va pas dans le code lui-même.

### ☐ 1.5 Vérifier le fuseau horaire

```powershell
python -c "from core.window import using_fallback_timezone, TZ; print('zone:', TZ); print('fallback:', using_fallback_timezone())"
```

**Attendu :**
```
zone: Africa/Casablanca
fallback: False
```

> Si `fallback: True`, `tzdata` manque. La fenêtre horaire dériverait d'une heure
> pendant le Ramadan. `python -m pip install tzdata`.

---

## 2. Tests SANS accès au portail  ⏱️ ~10 min

Ces tests prouvent que la base, la migration, l'API et le tableau de bord
fonctionnent — **aucun code SMS nécessaire**.

### ☐ 2.1 Créer la base

```powershell
python -m db.migrate
```

**Attendu :** les 4 comptes créés, puis un résumé :

```
    [+] mcma_oujda     MCMA — Oujda
    [+] mamda_oujda    MAMDA — Oujda
    [+] mcma_nador     MCMA — Nador
    [+] mamda_nador    MAMDA — Nador
...
    Comptes            : 4
```

Le fichier `data\mcma.db` doit maintenant exister.

### ☐ 2.2 La migration est rejouable

```powershell
python -m db.migrate
```

**Attendu :** aucune erreur, `Sinistres importés : 0 nouveaux`. La commande ne
crée pas de doublons — c'est important, l'agence pourrait la relancer par erreur.

### ☐ 2.3 Injecter des données de test

Puisqu'il n'y a pas encore d'alertes réelles, fabriquons-en :

```powershell
python -m tools.seed_test_data
```

**Attendu :**

```
[+] 3 nouveau(x) sinistre(s) de test sur 3 traité(s).
    - TEST-001   ALAOUI Mohamed       12345-A-7
    - TEST-002   BENNANI Fatima       67890-B-12
    - TEST-003   TAZI Youssef         WW123456
```

> Les trois références commencent par `TEST-` et vivent dans une catégorie
> dédiée. `python -m tools.seed_test_data --clear` les supprimera plus tard sans
> toucher aux sinistres réels.

### ☐ 2.4 Démarrer le serveur

Dans **cette même fenêtre PowerShell** (pour garder les variables de la §0.2) :

```powershell
python main.py
```

**Attendu — la bannière doit afficher :**

```
  ⏰  Horaires de synchronisation : 00:00 – 23:59 (toutes les 5 min)
  🌍  Fuseau horaire              : Africa/Casablanca
  📋  Portail actuellement        : OUVERT
  🛡️  Remplissage automatique     : DÉSACTIVÉ
```

> ✅ `Remplissage automatique : DÉSACTIVÉ` — c'est le point le plus important
> de tout ce test.

### ☐ 2.5 Le tableau de bord

Ouvrez <http://localhost:8000>.

| À vérifier | Attendu |
| :--- | :--- |
| ☐ Les **4 cartes de comptes** s'affichent en haut | toutes grises, « Jamais connecté » |
| ☐ Une fenêtre demande **« Qui êtes-vous ? »** | saisissez votre prénom |
| ☐ Le bouton en haut à droite affiche votre nom | |
| ☐ Les **3 sinistres de test** apparaissent dans le tableau | TEST-001, TEST-002, TEST-003 |
| ☐ Le bandeau orange « Portail fermé » est **absent** | (fenêtre forcée ouverte) |

### ☐ 2.6 Suivi du travail

| Action | Attendu |
| :--- | :--- |
| ☐ Cliquer la pastille ⚪ de TEST-001 | passe à 🔵 En Cours, petit toast en bas |
| ☐ Cliquer encore | 🟢 Traité, la ligne devient verte |
| ☐ Le KPI « Traité » | passe à 1 (33 %) |
| ☐ Cliquer ✏️ sur TEST-002, écrire une note, Enregistrer | le bouton Note devient plein |
| ☐ Rechercher `67890` | seul TEST-002 reste |
| ☐ Rechercher le texte de votre note | TEST-002 apparaît aussi |

### ☐ 2.7 🔑 Le test de persistance — le plus important

**Fermez complètement le navigateur**, rouvrez <http://localhost:8000>.

**Attendu :** TEST-001 est **toujours 🟢 Traité**, la note de TEST-002 est
**toujours là**.

> C'est ce qui prouve que les données vivent dans SQLite et non dans le
> navigateur. Avant, tout était dans `localStorage` : chaque employé voyait un
> état différent.

### ☐ 2.8 Vérifier l'attribution

```powershell
python -c "from db.repository import Repository; r=Repository(); [print(dict(x)) for x in r.conn.execute('SELECT claim_id, employee_status, note, updated_by FROM employee_actions')]; r.close()"
```

**Attendu :** `updated_by` contient **votre prénom**, pas `None`.

### ☐ 2.9 Le module de remplissage est bien bloqué

Dans une **2ᵉ** fenêtre PowerShell (laissez le serveur tourner) :

```powershell
curl.exe http://localhost:8000/health
```

**Attendu :** `"form_filling":false`

```powershell
try {
  Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/fill-dossier `
    -ContentType "application/json" -Body '{"payload":{}}'
  "PROBLEME : la requete a reussi, le module devrait etre desactive"
} catch {
  "Code HTTP : $($_.Exception.Response.StatusCode.value__)  (503 attendu)"
}
```

**Attendu :** code **503** et un message français expliquant que le module est
désactivé.

```powershell
python -m tools.run_dossier
```

**Attendu :** `[X] MODULE DESACTIVE`, puis sortie immédiate.

### ☐ 2.10 Les anciens points d'entrée ont disparu

```powershell
"/api/v1/notification-actions","/api/v1/cached-notifications","/api/v1/notifications" | ForEach-Object {
  try { Invoke-WebRequest "http://localhost:8000$_" -UseBasicParsing | Out-Null; "$_ -> 200 (PROBLEME)" }
  catch { "$_ -> $($_.Exception.Response.StatusCode.value__)" }
}
```

**Attendu :** `404` pour les deux. Ils écrivaient dans des fichiers JSON en
parallèle de la base — leur disparition est voulue.

---

## 3. Tests AVEC accès au portail  ⏱️ ~30 min

📱 **Ayez le téléphone qui reçoit les SMS.**

### ☐ 3.1 Connexion d'un compte

Sur le tableau de bord, cliquez **« Reconnecter »** sur la carte **MCMA — Oujda**.

**Attendu :**
1. Une fenêtre Chromium s'ouvre sur la page de connexion MCMA.
2. Vous saisissez identifiant + mot de passe + code SMS.
3. Dès l'arrivée sur le tableau de bord MCMA, la fenêtre se ferme seule.
4. **La carte passe au vert « Session active »** (au plus tard 15 s après).

> ⚠️ Si vous n'avez les identifiants que d'**un seul** compte, c'est suffisant.
> Les 3 autres cartes doivent simplement rester grises sans provoquer d'erreur —
> c'est en soi un test utile.

### ☐ 3.2 Première synchronisation réelle

Cliquez **« Actualiser »**.

| À vérifier | Attendu |
| :--- | :--- |
| ☐ Des sinistres **réels** apparaissent | références, immatriculations, sociétaires |
| ☐ Des **onglets de catégories** apparaissent | ex. MISSIONS (FACTURES REÇUES) |
| ☐ La carte du compte affiche « Dernière synchro : HH:MM » | |
| ☐ Le compteur d'alertes de la carte est cohérent | |

Dans la console du serveur, vous devez voir :
```
[HH:MM:SS] [poller] mcma_oujda: SUCCESS — N alerte(s), N nouvelle(s)
```

### ☐ 3.3 Synchronisation automatique

Ne touchez à rien pendant **5 minutes**.

**Attendu :** une nouvelle ligne `[poller] mcma_oujda: SUCCESS` apparaît toute
seule dans la console. C'est la fonctionnalité centrale de la Phase 1 : plus
personne n'a besoin de cliquer.

### ☐ 3.4 Les notes survivent à une synchronisation

1. Marquez un sinistre **réel** comme 🟢 Traité et ajoutez une note.
2. Cliquez **« Actualiser »**.

**Attendu :** le statut et la note sont **toujours là**.

> C'est le « double cycle de vie » : les données du portail se rafraîchissent,
> le travail des employés n'est jamais écrasé.

### ☐ 3.5 Test d'une catégorie en échec (facultatif, avancé)

Débranchez le réseau pendant une synchronisation, ou fermez brutalement.

**Attendu :** dans la console, `AUTH_FAILED` ou `UNREACHABLE`, et **aucun
sinistre ne disparaît du tableau**. Une synchronisation ratée ne doit jamais
archiver quoi que ce soit.

```powershell
python -c "from db.repository import Repository; r=Repository(); [print(dict(x)) for x in r.conn.execute('SELECT id,account_id,outcome,started_at FROM poll_runs ORDER BY id DESC LIMIT 5')]; r.close()"
```

---

## 4. Test multi-postes (réseau local)  ⏱️ ~10 min

### ☐ 4.1 Autoriser le port

PowerShell **en administrateur** — adaptez le sous-réseau au vôtre :

```powershell
netsh advfirewall firewall add rule name="MCMA TEST 8000" dir=in action=allow protocol=TCP localport=8000 profile=private remoteip=192.168.1.0/24
```

> 🧹 **À supprimer après le test :**
> `netsh advfirewall firewall delete rule name="MCMA TEST 8000"`

### ☐ 4.2 Depuis un 2ᵉ PC

Relevez l'IP affichée dans la bannière du serveur, puis ouvrez
`http://<IP>:8000` depuis un autre PC.

| À vérifier | Attendu |
| :--- | :--- |
| ☐ Le tableau de bord s'affiche | |
| ☐ On vous demande votre nom (différent du 1ᵉʳ) | |
| ☐ Les mêmes sinistres, les mêmes statuts | |

### ☐ 4.3 🔑 Le test de travail collaboratif

**PC A :** marquez un sinistre 🟢 Traité.
**PC B :** ne touchez à rien, attendez **15 secondes**.

**Attendu :** le changement apparaît **tout seul** sur le PC B.

> C'est le test qui prouve que le bug de perte d'écriture est corrigé. Avant,
> chaque navigateur avait sa propre copie et le dernier à rafraîchir écrasait
> le travail des autres.

---

## 5. Robustesse  ⏱️ ~5 min

### ☐ 5.1 Redémarrage

Arrêtez le serveur (`Ctrl+C`), relancez `python main.py`, rechargez la page.

**Attendu :** tout est là — sinistres, statuts, notes, sessions.

### ☐ 5.2 Serveur éteint

Arrêtez le serveur, gardez la page ouverte.

**Attendu :** l'indicateur en haut passe à **« Hors ligne »** au bout de ~15 s.
La page ne plante pas. Au redémarrage du serveur, elle se reconnecte seule.

### ☐ 5.3 Fenêtre horaire fermée

Fermez PowerShell (pour perdre les variables de la §0.2), rouvrez, puis :

```powershell
$env:MCMA_WINDOW_START = "23:58"
$env:MCMA_WINDOW_END   = "23:59"
python main.py
```

**Attendu :**
- Console : `[poller] hors fenêtre — aucune interrogation du portail.`
- Tableau de bord : **bandeau orange** « Portail MAMDA/MCMA fermé ».
- Les sinistres restent affichés, **rien n'est archivé**.

> C'est le comportement qui évite le pire scénario : un tableau de bord vide
> chaque matin parce que le système aurait archivé toute la file pendant la nuit.

---

## 6. Ce qui ne peut PAS encore être testé

| Élément | Pourquoi |
| :--- | :--- |
| **Les 4 comptes en parallèle** | il faut les 4 jeux d'identifiants et 4 codes SMS |
| **L'archivage après 3 synchros** | il faut qu'une alerte disparaisse réellement du portail |
| **Le remplissage automatique** | volontairement désactivé — ne pas activer |
| **Le démarrage automatique Windows** | à tester sur le vrai PC serveur, pas ici |
| **Le déploiement Ubuntu** | ⚠️ le serveur de l'entreprise est sous **Linux**, pas Windows. Le bouton « Reconnecter » ouvre un navigateur visible, ce qui est impossible via SSH. **Cette partie demandera une modification du code.** |

---

## 7. Dépannage

| Symptôme | Cause | Solution |
| :--- | :--- | :--- |
| `57 passed` non obtenu | code ou dépendances | notez la sortie, ne continuez pas |
| `fallback: True` sur le fuseau | `tzdata` absent | `python -m pip install tzdata` |
| Rien ne se synchronise | hors fenêtre horaire | §0.2 — forcez la fenêtre |
| Cartes de comptes vides | base non créée | `python -m db.migrate` |
| « Reconnecter » ne fait rien | hors fenêtre horaire | le portail refuse — message explicite attendu |
| `Port 8000 already in use` | serveur déjà lancé | fermez l'autre fenêtre |
| 2ᵉ PC ne voit rien | pare-feu | §4.1, et vérifiez le sous-réseau |
| Tableau vide après migration | pas encore d'alertes | normal — passez à la §2.3 ou §3.2 |

### Commandes de diagnostic

```powershell
python -m pytest -q                          # 57 passed attendu
curl.exe http://localhost:8000/health        # état du serveur + fenêtre
python -m tools.session_keeper --check       # session MCMA valide ?
python -c "from db.repository import Repository; r=Repository(); print(r.counts()); r.close()"
```

---

## 8. Fiche de résultats

À remplir pendant le test :

```
DATE : ____________          TESTEUR : ____________

PARTIE 1 — Installation
  [ ] 1.4  57 tests passent .................... OUI / NON  ____________
  [ ] 1.5  Fuseau Africa/Casablanca ............ OUI / NON

PARTIE 2 — Sans portail
  [ ] 2.1  Base créée, 4 comptes ............... OUI / NON
  [ ] 2.2  Migration rejouable sans doublon .... OUI / NON
  [ ] 2.4  Bannière : remplissage DÉSACTIVÉ .... OUI / NON
  [ ] 2.5  4 cartes + demande du nom ........... OUI / NON
  [ ] 2.6  Statuts et notes fonctionnent ....... OUI / NON
  [ ] 2.7  Persistance après fermeture ......... OUI / NON   <-- CRITIQUE
  [ ] 2.9  fill-dossier renvoie 503 ............ OUI / NON   <-- CRITIQUE
  [ ] 2.10 Anciens endpoints en 404 ............ OUI / NON

PARTIE 3 — Avec portail
  [ ] 3.1  Connexion + SMS, carte verte ........ OUI / NON
  [ ] 3.2  Alertes réelles affichées ........... OUI / NON   Nombre : ____
  [ ] 3.3  Synchro automatique à 5 min ......... OUI / NON
  [ ] 3.4  Notes survivent à la synchro ........ OUI / NON   <-- CRITIQUE

PARTIE 4 — Réseau
  [ ] 4.2  Accès depuis un 2e PC ............... OUI / NON
  [ ] 4.3  Changement visible en 15 s .......... OUI / NON   <-- CRITIQUE

PARTIE 5 — Robustesse
  [ ] 5.1  Données intactes après redémarrage .. OUI / NON
  [ ] 5.3  Fenêtre fermée : rien d'archivé ..... OUI / NON   <-- CRITIQUE

PROBLÈMES RENCONTRÉS :
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
```

### Les 6 tests critiques

Si l'un de ces six échoue, **ne déployez pas** :

1. **2.7** — les données survivent à la fermeture du navigateur
2. **2.9** — le remplissage automatique renvoie bien 503
3. **3.4** — les notes survivent à une synchronisation
4. **4.3** — le travail d'un collègue apparaît chez les autres
5. **5.3** — fenêtre fermée : aucun archivage
6. **1.4** — les 57 tests passent

---

## 9. Après le test

```powershell
# Supprimer la règle de pare-feu de test
netsh advfirewall firewall delete rule name="MCMA TEST 8000"

# Supprimer uniquement les sinistres de test
python -m tools.seed_test_data --clear

# Ou repartir totalement de zero (supprime toute la base de test)
Remove-Item -Recurse -Force data
```

Documents liés :

| Fichier | Contenu |
| :--- | :--- |
| `docs/GUIDE_INSTALLATION_AGENCE.md` | installation réelle (Windows) |
| `docs/PROJECT_ARCHITECTURE_BLUEPRINT.md` | architecture et décisions |
| `README.md` | vue d'ensemble et endpoints |
