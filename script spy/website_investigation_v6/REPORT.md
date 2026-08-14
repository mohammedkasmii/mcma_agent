# Website Investigation V6

Application: `https://sinauto.mamda-mcma.ma/`
Scope domain: `mamda-mcma.ma`

## Summary

- application: https://sinauto.mamda-mcma.ma/
- scope_domain: mamda-mcma.ma
- pages: 10
- forms: 95
- clicks: 66
- form_submissions: 2
- network_requests: 507
- business_api_requests: 78
- cross_origin_api_requests: 0
- infrastructure_requests: 0
- unique_business_endpoints: 17
- unique_form_write_endpoints: 15
- field_dependency_links: 0

## Business endpoints

### `POST` `/SinAuto_MCMA/expertise/FrontExpert/listeMissions`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [3, 5, 9]
- triggers: 6

### `POST` `/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8]
- triggers: 8
- request schema present (source: network):
  - `IdMission`: ['string']
  - `IdRapportDefDet`: ['string']
  - `IdRubrique`: ['string']
  - `LibRubrique`: ['string']
  - `MontantHT`: ['string']
  - `MontantTTC`: ['string']
  - `MontantVetuste`: ['string']
  - `TauxVetuste`: ['string']
  - `Taxe`: ['string']
  - `delete`: ['string']
  - `edit`: ['string']

### `POST` `/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8, 9]
- triggers: 14
- request schema present (source: network):
  - `AccordAdverse__S`: ['string']
  - `DateDevis__DA`: ['string']
  - `DateFinTravaux__DA`: ['string']
  - `DateMECVeh__DA`: ['string']
  - `DateRdvSoc__DA`: ['string']
  - `DateValDevis__DA`: ['string']
  - `Depasse20000__S`: ['string']
  - `Epaviste__S`: ['string']
  - `HeureFinTravaux__S`: ['string']
  - `HeureRdv__S`: ['string']
  - `IdMission__I`: ['string']
  - `IdSinistre__I`: ['string']
  - `IsConfirmMTACM__S`: ['string']
  - `Kilometrage__I`: ['string']
  - `MontantChargeMutuelle__M`: ['string']
  - `MontantChargeSocietaire__M`: ['string']
  - `MontantDommage__M`: ['string']
  - `MontantEpave__M`: ['string']
  - `MontantFranchise__M`: ['string']
  - `MontantRemise__M`: ['string']
  - `MontantReparation__M`: ['string']
  - `MontantTVA__M`: ['string']
  - `MontantVetuste__M`: ['string']
  - `MotifDesaccord__S`: ['string']
  - `NbreJourImmobilisation__I`: ['string']
  - `ObservationMission__S`: ['string']
  - `OffreEpave__M`: ['string']
  - `RappCarence__S`: ['string']
  - `ReferenceDossier__S`: ['string']
  - `TelEpaviste__S`: ['string']

### `POST` `/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [7, 8, 9]
- triggers: 14

### `POST` `/SinAuto_MCMA/expertise/gestionExpert/listeMissionExpert`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [7]

### `POST` `/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [7, 8, 9]
- triggers: 22
- request schema present (source: network):
  - `IdMission`: ['string']

### `GET` `/SinAuto_MCMA/expertise/notification/alerte`
- kinds: xhr_fetch_or_api_path
- pages: [4, 5, 6, 7, 8, 9, 10]
- triggers: 6

### `GET` `/SinAuto_MCMA/expertise/notification/ged`
- kinds: xhr_fetch_or_api_path
- pages: [6, 8, 9]
- triggers: 4

### `POST` `/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/67D9A055-75D1-47CF-A94E-70F4245DE751`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [4]
- triggers: 2

### `POST` `/SinAuto_MCMA/front/Login/login`
- kinds: form_or_navigation, html_form_submission
- pages: [2]
- triggers: 1
- request schema present (source: network):
  - `admin`: ['string']
  - `hashedPassword`: ['string']
  - `password`: ['string']
  - `token`: ['string']
  - `username`: ['string']

### `POST` `/SinAuto_MCMA/front/otp/verify`
- kinds: form_or_navigation, html_form_submission
- pages: [3]
- triggers: 1
- request schema present (source: network):
  - `otp-code`: ['string']

### `POST` `/SinAuto_MCMA/gestion/GED/ajouterDocument`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8, 9]
- triggers: 8
- request schema present (source: network):
  - `CodeEcran`: ['string']
  - `IdComplement`: ['string']
  - `IdFile`: ['string']
  - `NatureDocument`: ['string']

### `POST` `/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/810692`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8, 9]
- triggers: 8

### `POST` `/SinAuto_MCMA/gestion/GED/listDocuments`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8, 9]
- triggers: 16
- request schema present (source: network):
  - `CodeEcran`: ['string']
  - `IdComplement`: ['string']

### `POST` `/SinAuto_MCMA/gestion/GED/natureDocuments`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8, 9]
- triggers: 8
- request schema present (source: network):
  - `CodeEcran`: ['string']

### `POST` `/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [8]
- triggers: 8

### `POST` `/bf/4639051e-746e-412b-a942-74bd22627eea?`
- kinds: form_or_navigation, xhr_fetch_or_api_path
- pages: [2]
- triggers: 6

## Form/write endpoints (filtered view)

- `POST` `/SinAuto_MCMA/expertise/FrontExpert/listeMissions` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/expertise/gestionExpert/listeMissionExpert` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/67D9A055-75D1-47CF-A94E-70F4245DE751` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/front/Login/login` — form_or_navigation, html_form_submission
- `POST` `/SinAuto_MCMA/front/otp/verify` — form_or_navigation, html_form_submission
- `POST` `/SinAuto_MCMA/gestion/GED/ajouterDocument` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/810692` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/gestion/GED/listDocuments` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/gestion/GED/natureDocuments` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/` — form_or_navigation, xhr_fetch_or_api_path
- `POST` `/bf/4639051e-746e-412b-a942-74bd22627eea?` — form_or_navigation, xhr_fetch_or_api_path

## Field dependencies (response value reused in a later request)

None detected.

## Forms with select options / hidden fields / constraints

### Form `form`
- `token` (hidden) — hidden value redacted (sensitive-name, opaque-string, len=15)
- `hashedPassword` (hidden) — hidden value: ``
- `admin` (hidden) — hidden value: ``

### Form `form`
- `token` (hidden) — hidden value redacted (sensitive-name, opaque-string, len=15)
- `hashedPassword` (hidden) — hidden value: ``
- `admin` (hidden) — hidden value: ``

### Form `otp-form`
- `otp-code` (text) — maxlength: 6

### Form `otp-form`
- `otp-code` (text) — maxlength: 6

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ``
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: `N`
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: `N`
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: `N`
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: `N`
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: `N`
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `IdRubrique` (select-one) — options: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formMET`
- `IdNatureDocument__I` (select-one) — options: [, 49, 112, 113, 151, 111, 38, 9, 135, 136]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formExpertMission`
- `IdSinistre__I` (hidden) — hidden value: `810692`
- `IdMission__I` (hidden) — hidden value: `532805`
- `Depasse20000I` (checkbox) — 
- `Depasse20000__S` (hidden) — hidden value: ``
- `AccordI` (checkbox) — 
- `DesAccordI` (checkbox) — 
- `AccordAdverse__S` (hidden) — hidden value: ` `
- `VehRepareI` (checkbox) — 
- `VehReformeI` (checkbox) — 
- `VehReforme__S` (hidden) — hidden value: ``
- `TvaRecupI` (checkbox) — 
- `TvaRecup__S` (hidden) — hidden value: ``
- `RappCarenceI` (checkbox) — 
- `RappCarence__S` (hidden) — hidden value: ``
- `PartResponsabilite` (select-one) — options: [0, 50, 100]
- `IsConfirmMTACMI` (checkbox) — 
- `IsConfirmMTACM__S` (hidden) — hidden value: ``
- `TypeReforme__S` (select-one) — options: [, E, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]

### Form `formRecherche`
- `TypeMission__S` (select-one) — options: [, A, C, E, G, J, N, V]
- `Modereparation__I` (select-one) — options: [, N, C, A, S, B, T]


## Cross-origin API

None detected.

## Recent workflow

- CLICK page 8: `Enregistrer`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← Enregistrer
- CLICK page 8: `__/__/____`
- CLICK page 8: `Enregistrer`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← Enregistrer
- CLICK page 8: `Ajouter`
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/` ← Ajouter
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- CLICK page 8: `MontantHT`
- CLICK page 8: `None`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet` ← None
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← None
- CLICK page 8: `Ajouter`
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/` ← Ajouter
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- CLICK page 8: `MontantHT`
- CLICK page 8: `None`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet` ← None
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← None
- CLICK page 8: `Ajouter`
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/` ← Ajouter
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- API page 8: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/alerte`
- CLICK page 8: `MontantHT`
- CLICK page 8: `Taxe`
- CLICK page 8: `None`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet` ← None
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← None
- CLICK page 8: `Ajouter`
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/` ← Ajouter
- CLICK page 8: `FOURNITURES CARROSSERIE (ORIGINES)
FOURNITURES CARROSSERIE (ADAPTABLES)
FOURNITURES CARROSSERIE (RÉCUPÉRABLES)
FOURNITURES MÉCANIQUE (ORIGINES)
FOURNI`
- CLICK page 8: `MontantHT`
- CLICK page 8: `None`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet` ← None
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← None
- CLICK page 8: `Enregistrer`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← Enregistrer
- CLICK page 8: `GED`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments` ← GED
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/natureDocuments` ← GED
- CLICK page 8: `document`
- API page 8: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/alerte`
- CLICK page 8: `document`
- CLICK page 8: `Enregistrer`
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/810692` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument` ← Enregistrer
- API page 8: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/ged` ← Enregistrer
- API page 8: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments` ← Enregistrer
- CLICK page 8: `None`
- PAGE https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/ged/document/IdFile/5310976
- CLICK page 9: `NbreJourImmobilisation`
- CLICK page 9: `Enregistrer`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← Enregistrer
- CLICK page 9: `GED`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/natureDocuments` ← GED
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments` ← GED
- API page 9: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/alerte` ← GED
- CLICK page 9: `document`
- CLICK page 9: `Enregistrer`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/810692` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument` ← Enregistrer
- API page 9: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/ged` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments` ← Enregistrer
- CLICK page 9: `C:\fakepath\Photos_AVANT_dossier (1)_compressed.pdf`
- CLICK page 9: `Enregistrer`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/810692` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument` ← Enregistrer
- API page 9: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/ged` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments` ← Enregistrer
- CLICK page 9: `C:\fakepath\MCM22072026WEX704937.pdf`
- CLICK page 9: `Enregistrer`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/810692` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument` ← Enregistrer
- API page 9: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/ged` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments` ← Enregistrer
- CLICK page 9: `Enregistrer`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← Enregistrer
- CLICK page 9: `Enregistrer`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532805` ← Enregistrer
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` ← Enregistrer
- CLICK page 9: `None`
- API page 9: `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/listeMissions` ← None
- PAGE https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/frontExpert/
- API page 9: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/alerte` ← None
- API page 10: `GET https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/alerte`