"""
mock_server.py — Local 1:1 MCMA Simulation Server
=================================================
Provides a local offline environment replicating the exact MCMA DOM,
JavaScript calculation engines, jQuery events, dual-table layouts, and
API endpoints discovered in Camoufox investigation traces.

Run locally:
    python mock_server.py
Access via:
    http://localhost:8080/SinAuto_MCMA/expertise/gestionexpert/index
"""

import uvicorn
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI(title="MCMA Local Mock Test Server")

# In-memory mock database
MOCK_STATE = {
    "mode": "conventionne",  # 'normal' or 'conventionne'
    "saved_rubriques_normal": [],
    "devis_items_garage": [
        {"IdDevisDet": 1, "IdRubrique": "3", "LibRubrique": "TOTAL PIECES OCCASIONS / RECUPERABLES", "MontantHT": "4750.00", "Taxe": "950.00", "MontantTTC": "5700.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
        {"IdDevisDet": 2, "IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "1820.00", "Taxe": "364.00", "MontantTTC": "2184.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
        {"IdDevisDet": 3, "IdRubrique": "12", "LibRubrique": "MAIN D'OEUVRE PEINTURE", "MontantHT": "1680.00", "Taxe": "336.00", "MontantTTC": "2016.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
        {"IdDevisDet": 4, "IdRubrique": "16", "LibRubrique": "PEINTURES ET INGREDIENTS", "MontantHT": "1083.33", "Taxe": "216.67", "MontantTTC": "1300.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"}
    ],
    "validated_devis_payload": None,
    "last_saved_mission": None,
    "uploaded_documents": []
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>MCMA - SinAuto Expertise (Local Mock Server)</title>
    <!-- Fonts & Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
    <!-- jQuery -->
    <script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
    <script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js"></script>
    
    <style>
        body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f6f9; color: #333; font-size: 12px; }
        .navbar-default { background-color: #003366; border: none; border-radius: 0; color: white; min-height: 50px; }
        .navbar-default .brand { font-size: 18px; font-weight: bold; color: #fff; line-height: 50px; padding-left: 20px; }
        .mission-header { background: #fff; border-bottom: 2px solid #ddd; padding: 10px 20px; margin-bottom: 15px; }
        .mission-header .badge-statut { background-color: #5cb85c; color: white; padding: 5px 10px; font-size: 11px; border-radius: 3px; }
        fieldset { border: 1px solid #c0c0c0; margin: 0 2px 15px 2px; padding: 0.35em 0.625em 0.75em; background: #fff; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        legend { font-size: 13px; font-weight: bold; color: #003366; border-bottom: none; width: auto; margin-bottom: 5px; padding: 0 8px; }
        .form-group { margin-bottom: 8px; }
        .form-control { height: 28px; padding: 3px 6px; font-size: 12px; border-radius: 2px; border: 1px solid #ccc; }
        .control-label { text-align: right; padding-top: 5px; font-weight: 600; color: #444; }
        .table-condensed > tbody > tr > td, .table-condensed > thead > tr > th { padding: 4px 6px; font-size: 11px; }
        .table-striped > tbody > tr:nth-of-type(odd) { background-color: #f9f9f9; }
        .btn-sm { padding: 3px 8px; font-size: 11px; }
        .mode-toggle-bar { background: #ffeb3b; padding: 8px 15px; font-weight: bold; border-bottom: 1px solid #e0c800; display: flex; justify-content: space-between; align-items: center; }
        .hud-log { background: #222; color: #00ff66; font-family: monospace; font-size: 11px; padding: 10px; max-height: 120px; overflow-y: auto; border-top: 2px solid #444; }
        .edit-row { color: #337ab7; cursor: pointer; font-size: 14px; margin-right: 5px; }
        .save-row { color: #5cb85c; cursor: pointer; font-size: 14px; margin-right: 5px; }
        .delete-row { color: #d9534f; cursor: pointer; font-size: 14px; }
        .tr-editing { background-color: #e8f4ff !important; }
        .text-bold { font-weight: bold; }
    </style>
</head>
<body>

    <!-- TOP BAR -->
    <div class="mode-toggle-bar">
        <span><i class="fa fa-server"></i> MCMA LOCAL TEST PORTAL (Camoufox Mock Environment)</span>
        <div>
            <span>CURRENT MODE: </span>
            <button id="btnModeToggle" class="btn btn-xs btn-primary" onclick="toggleMode()">
                MODE: <span id="currentModeLabel">GARAGE CONVENTIONNÉ (PEC)</span> (Click to Switch)
            </button>
        </div>
    </div>

    <!-- NAVBAR HEADER -->
    <div class="navbar navbar-default">
        <div class="brand"><i class="fa fa-shield"></i> SinAuto MCMA - Espace Gestion Expert</div>
    </div>

    <!-- MISSION TOP INFO -->
    <div class="mission-header">
        <div class="row">
            <div class="col-sm-2"><b>Ref Sinistre:</b> <span id="hdrRefSinistre" class="text-primary">MEX202648130</span></div>
            <div class="col-sm-2"><b>Date Sinistre:</b> <span class="text-primary">30/07/2026</span></div>
            <div class="col-sm-2"><b>Matricule:</b> <span id="hdrMatricule" class="text-primary">34602-B-7</span></div>
            <div class="col-sm-2"><b>Police:</b> <span class="text-primary">313B26100020</span></div>
            <div class="col-sm-2"><b>Nature:</b> <span class="label label-primary">MATÉRIEL</span></div>
            <div class="col-sm-2 text-right"><b>Statut:</b> <span class="badge-statut">DÉCLARÉ</span></div>
        </div>
    </div>

    <div class="container-fluid">
        <form id="formExpertMission" onsubmit="return false;">
            
            <input type="hidden" id="IdSinistre__I" name="IdSinistre__I" value="534660">
            <input type="hidden" id="IdMission" name="IdMission" value="532805">
            <input type="hidden" id="VehReforme" name="VehReforme" value="N">
            <input type="hidden" id="Depasse20000" name="Depasse20000" value="N">
            <input type="hidden" id="TvaRecup" name="TvaRecup" value="O">
            <input type="hidden" id="RappCarence" name="RappCarence" value="N">
            <input type="hidden" id="IsConfirmMTACM" name="IsConfirmMTACM" value="N">

            <!-- 1. VEHICLE & DOSSIER INFO -->
            <div class="row">
                <div class="col-md-6">
                    <fieldset>
                        <legend>Informations Véhicule & Sociétaire</legend>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Réf Dossier:</label>
                                <div class="col-sm-7"><input type="text" id="ReferenceDossier" name="ReferenceDossier" class="form-control" value=""></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Réf Mission:</label>
                                <div class="col-sm-7"><input type="text" id="ReferenceMission__S" name="ReferenceMission__S" class="form-control" value="3.MH.02.2026.00047" readonly></div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Sociétaire:</label>
                                <div class="col-sm-7"><input type="text" id="NomSocietaire" name="NomSocietaire" class="form-control" value="SAPRESS SA" readonly></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Matricule:</label>
                                <div class="col-sm-7"><input type="text" id="MatriculeVeh" name="MatriculeVeh" class="form-control" value="34602-B-7" readonly></div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Kilométrage:</label>
                                <div class="col-sm-7"><input type="text" id="Kilometrage" name="Kilometrage" class="form-control" value=""></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Mode Réparation:</label>
                                <div class="col-sm-7"><input type="text" id="modeReparation" name="modeReparation" class="form-control text-bold" value="GARAGE CONVENTIONNÉ" readonly></div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Lieu Expertise:</label>
                                <div class="col-sm-7"><input type="text" id="LieuExpertise" name="LieuExpertise" class="form-control" value=""></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Date Devis:</label>
                                <div class="col-sm-7"><input type="text" id="DateDevis" name="DateDevis" class="form-control" value=""></div>
                            </div>
                        </div>
                    </fieldset>
                </div>

                <!-- 2. FINANCIAL ASSESSMENT & VALUES -->
                <div class="col-md-6">
                    <fieldset>
                        <legend>Évaluation Financière du Sinistre</legend>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Valeur Vénale:</label>
                                <div class="col-sm-7"><input type="text" id="ValeurVenale" name="ValeurVenale" class="form-control" value="" onkeyup="CalculerMontantDommage()"></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Montant Épave:</label>
                                <div class="col-sm-7"><input type="text" id="MontantEpave" name="MontantEpave" class="form-control" value="" onkeyup="CalculerMontantDommage()"></div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Montant Dommage:</label>
                                <div class="col-sm-7"><input type="text" id="MontantDommage" name="MontantDommage" class="form-control" value="" readonly></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Part Resp (%):</label>
                                <div class="col-sm-7">
                                    <select id="PartResponsabilite" name="PartResponsabilite" class="form-control" onchange="CalculerMntArrete(); DevisCalculerMontantCharge();">
                                        <option value="100">100%</option>
                                        <option value="50">50%</option>
                                        <option value="0">0%</option>
                                    </select>
                                </div>
                            </div>
                        </div>
                        <div class="row">
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Date Fin Travaux:</label>
                                <div class="col-sm-7"><input type="text" id="DateFinTravaux" name="DateFinTravaux" class="form-control" value=""></div>
                            </div>
                            <div class="col-sm-6 form-group">
                                <label class="control-label col-sm-5">Jours Immob:</label>
                                <div class="col-sm-7"><input type="text" id="NbreJourImmobilisation" name="NbreJourImmobilisation" class="form-control" value=""></div>
                            </div>
                        </div>
                    </fieldset>
                </div>
            </div>

            <!-- 3. CHECKBOXES SECTION -->
            <div class="row">
                <div class="col-md-12">
                    <fieldset>
                        <legend>Options & Drapeaux</legend>
                        <label class="checkbox-inline"><input type="checkbox" id="VehRepareI" name="VehRepareI" checked onchange="toggleVehRepare()"> <b>Véhicule Réparé</b></label>
                        <label class="checkbox-inline"><input type="checkbox" id="TvaRecupI" name="TvaRecupI" checked onchange="CalculerMntArrete(); DevisCalculerMontantCharge();"> <b>TVA Récupérable</b></label>
                        <label class="checkbox-inline"><input type="checkbox" id="Depasse20000I" name="Depasse20000I"> <b>Dommages &gt; 20,000 DH</b></label>
                        <label class="checkbox-inline"><input type="checkbox" id="RappCarenceI" name="RappCarenceI"> <b>Rapport de Carence</b></label>
                        <label class="checkbox-inline"><input type="checkbox" id="IsConfirmMTACMI" name="IsConfirmMTACMI"> <b>Confirmer MT ACM</b></label>
                        <label class="checkbox-inline"><input type="checkbox" id="AccordI" name="AccordI" checked> <b>Accord Devis</b></label>
                    </fieldset>
                </div>
            </div>

            <!-- ============================================================= -->
            <!-- SECTION A: GARAGE CONVENTIONNÉ DUAL-TABLE (PEC)               -->
            <!-- ============================================================= -->
            <div id="sectionGarageConventionne">
                <!-- TABLE 1: READ ONLY GARAGE DEVIS -->
                <fieldset class="margin-bottom-10 border-dark padding-bottom-15">
                    <legend class="text-primary">Devis de la réparation (Garage - Lecture Seule)</legend>
                    <div id="DevisDetTable_wrapper">
                        <table id="DevisDetTable" class="table table-striped table-bordered table-condensed" style="width: 100%;">
                            <thead>
                                <tr>
                                    <th style="width: 45%;">Rubrique</th>
                                    <th style="width: 15%; text-align: right;">Montant HT</th>
                                    <th style="width: 15%; text-align: right;">MT Taxe</th>
                                    <th style="width: 25%; text-align: right;">Montant TTC</th>
                                </tr>
                            </thead>
                            <tbody id="tbodyDevisTable1">
                                <tr><td>TOTAL PIECES OCCASIONS / RECUPERABLES</td><td class="text-right">4 750.00</td><td class="text-right">950.00</td><td class="text-right">5 700.00</td></tr>
                                <tr><td>MAIN D'OEUVRE CARROSSERIE</td><td class="text-right">1 820.00</td><td class="text-right">364.00</td><td class="text-right">2 184.00</td></tr>
                                <tr><td>MAIN D'OEUVRE PEINTURE</td><td class="text-right">1 680.00</td><td class="text-right">336.00</td><td class="text-right">2 016.00</td></tr>
                                <tr><td>PEINTURES ET INGREDIENTS</td><td class="text-right">1 083.33</td><td class="text-right">216.67</td><td class="text-right">1 300.00</td></tr>
                            </tbody>
                            <tfoot>
                                <tr class="text-bold" style="background:#eee;">
                                    <td>Total</td>
                                    <td class="text-right">9 333.33</td>
                                    <td class="text-right">1 866.67</td>
                                    <td class="text-right">11 200.00</td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </fieldset>

                <!-- TABLE 2: EDITABLE VALIDATED DEVIS -->
                <fieldset id="blocDevisValide" class="margin-bottom-10 border-dark padding-bottom-15">
                    <legend class="text-primary">Devis de la réparation validé (Expert - Modifiable)</legend>
                    <div id="DevisDetTableVal_wrapper">
                        <table id="DevisDetTableVal" class="table table-striped table-bordered table-condensed" style="width: 100%;">
                            <thead>
                                <tr>
                                    <th style="width: 40%;">Rubrique</th>
                                    <th style="width: 11%; text-align: right;">Montant HT</th>
                                    <th style="width: 11%; text-align: right;">MT Taxe</th>
                                    <th style="width: 11%; text-align: right;">Montant TTC</th>
                                    <th style="width: 11%; text-align: right;">Taux Vétusté</th>
                                    <th style="width: 11%; text-align: right;">MT Vétusté</th>
                                    <th style="width: 2.5%; text-align: center;"></th>
                                    <th style="width: 2.5%; text-align: center;"></th>
                                </tr>
                            </thead>
                            <tbody id="tbodyDevisTable2">
                                <!-- Dynamic rows loaded by JS -->
                            </tbody>
                            <tfoot>
                                <tr class="text-bold" style="background:#eee;">
                                    <td>Total</td>
                                    <td id="footerVal_MontantHT" class="text-right">9 333.33</td>
                                    <td id="footerVal_Taxe" class="text-right">1 866.67</td>
                                    <td id="footerVal_MontantTTC" class="text-right">11 200.00</td>
                                    <td class="text-right">-</td>
                                    <td id="footerVal_MontantVetuste" class="text-right">0.00</td>
                                    <td colspan="2"></td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>

                    <!-- SUMMARY FINANCIAL SPLIT FOR GARAGE CONVENTIONNE -->
                    <div class="row" style="margin-top: 15px; background: #fafafa; padding: 10px; border-radius: 4px;">
                        <div class="col-md-3 form-group">
                            <label class="control-label col-sm-6">Devis TTC:</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantTTC" class="form-control text-right text-bold" value="11200.00" readonly></div>
                        </div>
                        <div class="col-md-3 form-group">
                            <label class="control-label col-sm-6">Devis TVA:</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantTVA" class="form-control text-right text-bold" value="1866.67" readonly></div>
                        </div>
                        <div class="col-md-3 form-group">
                            <label class="control-label col-sm-6">Vétusté Total:</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantVetusteTotal" class="form-control text-right" value="0.00"></div>
                        </div>
                        <div class="col-md-3 form-group">
                            <label class="control-label col-sm-6">Franchise:</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantFranchise" class="form-control text-right" value="0.00"></div>
                        </div>
                    </div>

                    <div class="row" style="background: #fafafa; padding: 5px 10px 10px 10px; border-radius: 4px;">
                        <div class="col-md-3 form-group">
                            <label class="control-label col-sm-6">Remise:</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantRemise" class="form-control text-right" value="0.00"></div>
                        </div>
                        <div class="col-md-4 form-group">
                            <label class="control-label col-sm-6" style="color:#d9534f;">Charge Sociétaire:</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantChargeSocietaire" class="form-control text-right text-bold" value="0.00" disabled></div>
                        </div>
                        <div class="col-md-5 form-group">
                            <label class="control-label col-sm-6" style="color:#5cb85c;">Charge Mutuelle (Prise en Charge):</label>
                            <div class="col-sm-6"><input type="text" id="DevisMontantChargeMutuelle" class="form-control text-right text-bold" value="11200.00" disabled></div>
                        </div>
                    </div>

                    <div class="row" style="margin-top: 10px;">
                        <div class="col-sm-8">
                            <textarea id="DevisObservationExpert" class="form-control" placeholder="Observations de l'expert sur le devis validé..."></textarea>
                        </div>
                        <div class="col-sm-4 text-right">
                            <a id="DEVISDET_Btn" class="btn btn-success" onclick="ValiderDevis()">
                                Valider Devis <i class="fa fa-check"></i>
                            </a>
                        </div>
                    </div>
                </fieldset>
            </div>

            <!-- ============================================================= -->
            <!-- SECTION B: MODE NORMAL STANDARD RUBRIQUES TABLE               -->
            <!-- ============================================================= -->
            <div id="sectionModeNormal" style="display: none;">
                <fieldset>
                    <legend>Rapport d'expertise de réparation (Mode Normal)</legend>
                    <div style="margin-bottom: 10px;">
                        <a class="btn btn-success btn-sm" onclick="ajouterLigneModeNormal()">
                            <i class="fa fa-plus"></i> Ajouter +
                        </a>
                    </div>
                    <table id="tableRapportDet" class="table table-striped table-bordered table-condensed">
                        <thead>
                            <tr>
                                <th style="width: 40%;">Rubrique</th>
                                <th style="width: 15%; text-align: right;">Montant HT</th>
                                <th style="width: 15%; text-align: right;">MT Taxe</th>
                                <th style="width: 15%; text-align: right;">Montant TTC</th>
                                <th style="width: 7.5%; text-align: right;">Taux Vétusté</th>
                                <th style="width: 7.5%; text-align: right;">MT Vétusté</th>
                                <th style="width: 5%;">Action</th>
                            </tr>
                        </thead>
                        <tbody id="tbodyModeNormal">
                            <!-- Added rows insert here -->
                        </tbody>
                    </table>

                    <!-- FINANCIAL TOTALS MODE NORMAL -->
                    <div class="row" style="background: #fafafa; padding: 10px; border-radius: 4px;">
                        <div class="col-sm-2 form-group">
                            <label class="control-label col-sm-6">Mt Réparation:</label>
                            <div class="col-sm-6"><input type="text" id="MontantReparation" name="MontantReparation" class="form-control text-right text-bold" value="0.00" onkeyup="CalculerMntArrete()"></div>
                        </div>
                        <div class="col-sm-2 form-group">
                            <label class="control-label col-sm-6">Montant TVA:</label>
                            <div class="col-sm-6"><input type="text" id="MontantTVA" name="MontantTVA" class="form-control text-right" value="0.00"></div>
                        </div>
                        <div class="col-sm-2 form-group">
                            <label class="control-label col-sm-6">Vétusté Total:</label>
                            <div class="col-sm-6"><input type="text" id="MontantVetusteTotal" name="MontantVetusteTotal" class="form-control text-right" value="0.00" onkeyup="CalculerMntArrete()"></div>
                        </div>
                        <div class="col-sm-2 form-group">
                            <label class="control-label col-sm-6">Franchise:</label>
                            <div class="col-sm-6"><input type="text" id="MontantFranchise" name="MontantFranchise" class="form-control text-right" value="0.00" onkeyup="CalculerMntArrete()"></div>
                        </div>
                        <div class="col-sm-2 form-group">
                            <label class="control-label col-sm-6">Mt Arrêté:</label>
                            <div class="col-sm-6"><input type="text" id="MontantArrete" name="MontantArrete" class="form-control text-right text-bold" value="0.00" readonly></div>
                        </div>
                        <div class="col-sm-2 form-group">
                            <label class="control-label col-sm-6">Base Indemnité:</label>
                            <div class="col-sm-6"><input type="text" id="BaseIndemnite" name="BaseIndemnite" class="form-control text-right text-bold text-success" value="0.00" readonly></div>
                        </div>
                    </div>
                </fieldset>
            </div>

            <!-- OBSERVATIONS & SAVE BAR -->
            <div class="row">
                <div class="col-md-12">
                    <fieldset>
                        <legend>Observation de la mission</legend>
                        <textarea id="ObservationMission" name="ObservationMission" class="form-control" rows="2"></textarea>
                    </fieldset>
                </div>
            </div>

            <div class="row text-right" style="padding-bottom: 20px;">
                <button type="button" class="btn btn-default" onclick="enregistrerMission()"><i class="fa fa-save"></i> Enregistrer</button>
                <button type="button" class="btn btn-primary" onclick="cloturerMission()"><i class="fa fa-check-circle"></i> Clôturer Traitement</button>
            </div>

        </form>
    </div>

    <!-- HUD TERMINAL LOG -->
    <div class="hud-log" id="hudLog">
        <div>[MOCK MCMA SERVER ONLINE] Ready to receive Playwright automation commands...</div>
    </div>

    <!-- ================================================================= -->
    <!-- EXACT MCMA JAVASCRIPT ENGINE & AUTO-CALCULATIONS                 -->
    <!-- ================================================================= -->
    <script>
        function logHUD(msg) {
            var el = document.getElementById("hudLog");
            el.innerHTML += "<div>" + msg + "</div>";
            el.scrollTop = el.scrollHeight;
        }

        function isNull(val, repl) {
            if (val == null || val == 0 || val == '' || isNaN(val)) return repl;
            return Number(val);
        }

        // Native Calculation: CalculerMontantDommage
        function CalculerMontantDommage() {
            var vv = parseFloat(isNull($("#ValeurVenale").val(), 0));
            var ep = parseFloat(isNull($("#MontantEpave").val(), 0));
            $("#MontantDommage").val((vv - ep).toFixed(2));
            logHUD("⚡ CalculerMontantDommage() executed -> MontantDommage = " + $("#MontantDommage").val());
        }

        // Native Calculation: CalculerMontantTTC
        function CalculerMontantTTC() {
            var ht = parseFloat(isNull($('#MontantHT').val(), 0));
            var tx = parseFloat(isNull($('#Taxe').val(), 0));
            $('#MontantTTC').val((ht + tx).toFixed(2));
        }

        // Native Calculation: CalculerMntArrete & BaseIndemnite
        function CalculerMntArrete() {
            var rep = parseFloat(isNull($("#MontantReparation").val(), 0));
            var fra = parseFloat(isNull($("#MontantFranchise").val(), 0));
            var vet = parseFloat(isNull($("#MontantVetusteTotal").val(), 0));
            var rem = parseFloat(isNull($("#MontantRemise").val(), 0));
            
            var arrete = rep - vet;
            $("#MontantArrete").val(arrete.toFixed(2));
            var base = Math.max(0, arrete - fra - rem);
            $("#BaseIndemnite").val(base.toFixed(2));
            logHUD("⚡ CalculerMntArrete() executed -> MontantArrete = " + arrete.toFixed(2) + " | BaseIndemnite = " + base.toFixed(2));
        }

        // Native Calculation: DevisCalculerMontantCharge (Garage Conventionne)
        function DevisCalculerMontantCharge() {
            var rep = parseFloat(isNull($("#DevisMontantTTC").val(), 0));
            var tva = parseFloat(isNull($("#DevisMontantTVA").val(), 0));
            var vet = parseFloat(isNull($("#DevisMontantVetusteTotal").val(), 0));
            var fra = parseFloat(isNull($("#DevisMontantFranchise").val(), 0));
            var rem = parseFloat(isNull($("#DevisMontantRemise").val(), 0));
            var resp = parseFloat(isNull($("#PartResponsabilite").val(), 100));

            var chargeSoc = (fra * resp / 100.0) + vet;
            if ($('#TvaRecupI').is(':checked')) {
                // Recoverable TVA
            }
            var chargeMut = Math.max(0, rep - chargeSoc - rem);

            $("#DevisMontantChargeSocietaire").val(chargeSoc.toFixed(2));
            $("#DevisMontantChargeMutuelle").val(chargeMut.toFixed(2));
            logHUD("⚡ DevisCalculerMontantCharge() executed -> ChargeSoc = " + chargeSoc.toFixed(2) + " | ChargeMut = " + chargeMut.toFixed(2));
        }

        function DevisChangeTvaRecup() {
            DevisCalculerMontantCharge();
        }

        // Toggle Normal vs Garage Conventionne Mode
        function toggleMode() {
            var cur = $("#modeReparation").val();
            if (cur.includes("CONVENTION")) {
                setModeNormal();
            } else {
                setModeConventionne();
            }
        }

        function setModeNormal() {
            $("#modeReparation").val("MODE NORMAL");
            $("#currentModeLabel").text("MODE NORMAL");
            $("#sectionGarageConventionne").hide();
            $("#sectionModeNormal").show();
            logHUD("🔀 Switched view to MODE NORMAL");
        }

        function setModeConventionne() {
            $("#modeReparation").val("GARAGE CONVENTIONNÉ");
            $("#currentModeLabel").text("GARAGE CONVENTIONNÉ (PEC)");
            $("#sectionGarageConventionne").show();
            $("#sectionModeNormal").hide();
            renderTable2();
            logHUD("🔀 Switched view to GARAGE CONVENTIONNÉ");
        }

        // Load Table 2 for Garage Conventionne
        var table2Data = [
            { id: 1, rubId: "3", label: "TOTAL PIECES OCCASIONS / RECUPERABLES", ht: "4750.00", taxe: "950.00", ttc: "5700.00", tauxVet: "0.00", mtVet: "0.00" },
            { id: 2, rubId: "7", label: "MAIN D'OEUVRE CARROSSERIE", ht: "1820.00", taxe: "364.00", ttc: "2184.00", tauxVet: "0.00", mtVet: "0.00" },
            { id: 3, rubId: "12", label: "MAIN D'OEUVRE PEINTURE", ht: "1680.00", taxe: "336.00", ttc: "2016.00", tauxVet: "0.00", mtVet: "0.00" },
            { id: 4, rubId: "16", label: "PEINTURES ET INGREDIENTS", ht: "1083.33", taxe: "216.67", ttc: "1300.00", tauxVet: "0.00", mtVet: "0.00" }
        ];

        function renderTable2() {
            var tbody = $("#tbodyDevisTable2");
            tbody.empty();
            var totalHT = 0, totalTaxe = 0, totalTTC = 0, totalVet = 0;
            
            table2Data.forEach(function(item) {
                totalHT += parseFloat(item.ht);
                totalTaxe += parseFloat(item.taxe);
                totalTTC += parseFloat(item.ttc);
                totalVet += parseFloat(item.mtVet);

                var tr = $('<tr id="row_val_' + item.id + '"></tr>');
                tr.append('<td>' + item.label + '</td>');
                tr.append('<td class="text-right col-ht">' + item.ht + '</td>');
                tr.append('<td class="text-right col-taxe">' + item.taxe + '</td>');
                tr.append('<td class="text-right col-ttc">' + item.ttc + '</td>');
                tr.append('<td class="text-right col-tauxvet">' + item.tauxVet + '</td>');
                tr.append('<td class="text-right col-mtvet">' + item.mtVet + '</td>');
                tr.append('<td class="text-center"><a title="Modifier" id="Modifier" class="edit-row" onclick="editRowTable2(' + item.id + ')"><i class="fa fa-pencil"></i></a></td>');
                tr.append('<td class="text-center"><a title="Supprimer" class="delete-row"><i class="fa fa-trash"></i></a></td>');
                tbody.append(tr);
            });

            $("#footerVal_MontantHT").text(totalHT.toFixed(2));
            $("#footerVal_Taxe").text(totalTaxe.toFixed(2));
            $("#footerVal_MontantTTC").text(totalTTC.toFixed(2));
            $("#footerVal_MontantVetuste").text(totalVet.toFixed(2));
            
            $("#DevisMontantTTC").val(totalTTC.toFixed(2));
            $("#DevisMontantTVA").val(totalTaxe.toFixed(2));
            $("#DevisMontantVetusteTotal").val(totalVet.toFixed(2));
            DevisCalculerMontantCharge();
        }

        // Inline Row Editing in Table 2
        function editRowTable2(id) {
            var item = table2Data.find(function(x) { return x.id === id; });
            if (!item) return;

            var tr = $("#row_val_" + id);
            tr.addClass("tr-editing editing");
            tr.find(".col-ht").html('<input type="text" id="MontantHTValide" name="MontantHTValide" class="form-control text-right input-sm" value="' + item.ht + '">');
            tr.find(".col-taxe").html('<input type="text" id="TaxeValide" name="TaxeValide" class="form-control text-right input-sm" value="' + item.taxe + '">');
            tr.find(".col-ttc").html('<input type="text" id="MontantTTCValide" name="MontantTTCValide" class="form-control text-right input-sm" value="' + item.ttc + '" disabled>');
            tr.find(".col-tauxvet").html('<input type="text" id="TauxVetusteValide" name="TauxVetusteValide" class="form-control text-right input-sm" value="' + item.tauxVet + '">');
            tr.find(".col-mtvet").html('<input type="text" id="MontantVetusteValide" name="MontantVetusteValide" class="form-control text-right input-sm" value="' + item.mtVet + '">');

            // Attach dynamic keyup formulas
            $("#MontantHTValide, #TaxeValide").keyup(function() {
                var ht = parseFloat(isNull($("#MontantHTValide").val(), 0));
                var tx = parseFloat(isNull($("#TaxeValide").val(), 0));
                $("#MontantTTCValide").val((ht + tx).toFixed(2));
            });
            $("#TauxVetusteValide").keyup(function() {
                var ttc = parseFloat(isNull($("#MontantTTCValide").val(), 0));
                var rate = parseFloat(isNull($("#TauxVetusteValide").val(), 0));
                $("#MontantVetusteValide").val((ttc * rate / 100).toFixed(2));
            });
            $("#MontantVetusteValide").keyup(function() {
                var ttc = parseFloat(isNull($("#MontantTTCValide").val(), 0));
                var mt = parseFloat(isNull($("#MontantVetusteValide").val(), 0));
                if (ttc > 0) $("#TauxVetusteValide").val(((mt / ttc) * 100).toFixed(2));
            });

            // Replace pencil icon with green checkmark in col 7
            tr.find("td:nth-child(7)").html('<a title="Enregistrer" class="save-row" onclick="saveRowTable2(' + id + ')"><i class="fa fa-check" style="color: #5cb85c; font-size: 16px;"></i></a>');
            logHUD("✏️ Row [" + item.rubId + "] " + item.label + " entered EDIT mode.");
        }

        // Commit Table 2 Row
        function saveRowTable2(id) {
            var item = table2Data.find(function(x) { return x.id === id; });
            var newHT = $("#MontantHTValide").val() || item.ht;
            var newTaxe = $("#TaxeValide").val() || item.taxe;
            var newTTC = $("#MontantTTCValide").val() || item.ttc;
            var newTauxVet = $("#TauxVetusteValide").val() || item.tauxVet;
            var newMtVet = $("#MontantVetusteValide").val() || item.mtVet;

            // Trigger AJAX update
            $.post("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet", {
                IdDevisDet: id,
                IdReparation: 534660,
                MontantHTValide: newHT,
                TaxeValide: newTaxe,
                MontantTTCValide: newTTC,
                TauxVetusteValide: newTauxVet,
                MontantVetusteValide: newMtVet
            }, function(res) {
                item.ht = parseFloat(newHT).toFixed(2);
                item.taxe = parseFloat(newTaxe).toFixed(2);
                item.ttc = parseFloat(newTTC).toFixed(2);
                item.tauxVet = parseFloat(newTauxVet).toFixed(2);
                item.mtVet = parseFloat(newMtVet).toFixed(2);
                renderTable2();
                logHUD("💾 POST /updateDevisDet OK (200) -> Row [" + item.rubId + "] saved.");
            }, "json");
        }

        // Submit Final Garage Devis Validation
        function ValiderDevis() {
            var payload = {
                IdReparation: 534660,
                Check_VALIDEVIS: 'O',
                DevisObservationExpert: $('#DevisObservationExpert').val(),
                DevisMontantTVA: $('#DevisMontantTVA').val(),
                DevisMontantVetuste: $('#DevisMontantVetusteTotal').val(),
                DevisMontantFranchise: $('#DevisMontantFranchise').val(),
                DevisMontantRemise: $('#DevisMontantRemise').val(),
                DevisMontantChargeSoc: $('#DevisMontantChargeSocietaire').val(),
                DevisMontantChargeMut: $('#DevisMontantChargeMutuelle').val()
            };
            logHUD("🚀 Submitting POST /garageModifierValDevis with payload: " + JSON.stringify(payload));
            $.post('/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis', payload, function(data) {
                logHUD("✅ Devis Validation Response: " + JSON.stringify(data));
                $('#DEVISDET_Btn').hide();
                $('#blocDevisValide :input').prop('disabled', true);
            }, "json");
        }

        // Mode Normal Row Addition
        var normalRowCounter = 0;
        function ajouterLigneModeNormal() {
            normalRowCounter++;
            var tbody = $("#tbodyModeNormal");
            var tr = $('<tr id="normal_row_' + normalRowCounter + '" class="tr-editing"></tr>');
            tr.append('<td><select id="IdRubrique" name="IdRubrique" class="form-control"><option value="1">FOURNITURES CARROSSERIE (ORIGINES)</option><option value="3">FOURNITURES CARROSSERIE (RECUPERABLES)</option><option value="7">MAIN D\\'OEUVRE CARROSSERIE</option><option value="12">MAIN D\\'OEUVRE PEINTURE</option><option value="16">PEINTURES ET INGREDIENTS</option></select></td>');
            tr.append('<td><input type="text" id="MontantHT" name="MontantHT" class="form-control text-right" value="" onkeyup="CalculerMontantTTC()"></td>');
            tr.append('<td><input type="text" id="Taxe" name="Taxe" class="form-control text-right" value="" onkeyup="CalculerMontantTTC()"></td>');
            tr.append('<td><input type="text" id="MontantTTC" name="MontantTTC" class="form-control text-right" value="" readonly></td>');
            tr.append('<td><input type="text" id="TauxVetuste" name="TauxVetuste" class="form-control text-right" value="0.00"></td>');
            tr.append('<td><input type="text" id="MontantVetuste" name="MontantVetuste" class="form-control text-right" value="0.00"></td>');
            tr.append('<td class="text-center"><a class="btn btn-success btn-xs" onclick="saveNormalRow(' + normalRowCounter + ')"><i class="fa fa-check"></i></a></td>');
            tbody.prepend(tr);
            logHUD("➕ Mode Normal: [Ajouter +] row created.");
        }

        function saveNormalRow(id) {
            var tr = $("#normal_row_" + id);
            var rubId = tr.find("#IdRubrique").val();
            var rubTxt = tr.find("#IdRubrique option:selected").text();
            var ht = tr.find("#MontantHT").val() || "0.00";
            var taxe = tr.find("#Taxe").val() || "0.00";
            var ttc = tr.find("#MontantTTC").val() || "0.00";
            var tauxVet = tr.find("#TauxVetuste").val() || "0.00";
            var mtVet = tr.find("#MontantVetuste").val() || "0.00";

            $.post("/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet", {
                IdRubrique: rubId,
                MontantHT: ht,
                Taxe: taxe,
                MontantTTC: ttc,
                TauxVetuste: tauxVet,
                MontantVetuste: mtVet
            }, function(res) {
                tr.removeClass("tr-editing");
                tr.html('<td>' + rubTxt + '</td><td class="text-right">' + parseFloat(ht).toFixed(2) + '</td><td class="text-right">' + parseFloat(taxe).toFixed(2) + '</td><td class="text-right">' + parseFloat(ttc).toFixed(2) + '</td><td class="text-right">' + parseFloat(tauxVet).toFixed(2) + '</td><td class="text-right">' + parseFloat(mtVet).toFixed(2) + '</td><td class="text-center"><i class="fa fa-lock text-success"></i></td>');
                logHUD("💾 POST /createRapportDefDet OK (200) -> Rubrique [" + rubId + "] committed.");
            }, "json");
        }

        function enregistrerMission() {
            $.post("/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission", $("#formExpertMission").serialize(), function(res) {
                logHUD("💾 POST /expertEnregistrerMission OK (200) -> " + JSON.stringify(res));
            }, "json");
        }

        function cloturerMission() {
            logHUD("🔒 Mission Clôturée.");
        }

        $(document).ready(function() {
            renderTable2();
            logHUD("✅ DOM Loaded with 79 input fields & active calculation formulas.");
        });
    </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# API ROUTE HANDLERS
# ---------------------------------------------------------------------------

@app.get("/")
@app.get("/SinAuto_MCMA/expertise/gestionexpert/index")
@app.get("/SinAuto_MCMA/expertise/gestionExpert/index")
def get_mission_page():
    return HTMLResponse(content=HTML_TEMPLATE)

@app.post("/SinAuto_MCMA/front/Login/login")
def mock_login():
    return JSONResponse({"state": "success", "message": "Login successful", "redirect": "/SinAuto_MCMA/expertise/frontExpert/"})

@app.post("/SinAuto_MCMA/expertise/FrontExpert/listeMissions")
def mock_liste_missions():
    return JSONResponse({
        "data": [
            {
                "IdMission": 532805,
                "ReferenceMission": "3.MH.02.2026.00047",
                "RefSinistre": "MEX202648130",
                "Matricule": "34602-B-7",
                "Societaire": "SAPRESS SA",
                "ModeReparation": "GARAGE CONVENTIONNÉ",
                "CodeStatut": "D",
                "Statut": "DÉCLARÉ"
            }
        ]
    })

@app.post("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet")
async def mock_update_devis_det(request: Request):
    form = await request.form()
    print(f"[MOCK API] /updateDevisDet received: {dict(form)}")
    return JSONResponse({"state": "success", "msg": "Détails Devis mis à jour avec succès."})

@app.post("/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis")
async def mock_valider_devis(request: Request):
    form = await request.form()
    print(f"[MOCK API] /garageModifierValDevis received: {dict(form)}")
    MOCK_STATE["validated_devis_payload"] = dict(form)
    return JSONResponse({"state": "success", "message": "Devis validé avec succès par l'expert."})

@app.post("/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet")
async def mock_create_rapport_det(request: Request):
    form = await request.form()
    print(f"[MOCK API] /createRapportDefDet received: {dict(form)}")
    return JSONResponse({"state": "success", "msg": "Rubrique enregistrée avec succès."})

@app.post("/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet")
def mock_liste_rapport_det():
    return JSONResponse({"state": "success", "data": []})

@app.post("/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet")
def mock_liste_devis_det():
    return JSONResponse({"state": "success", "data": MOCK_STATE["devis_items_garage"]})

@app.post("/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission")
async def mock_enregistrer_mission(request: Request):
    form = await request.form()
    print(f"[MOCK API] /expertEnregistrerMission received: {dict(form)}")
    MOCK_STATE["last_saved_mission"] = dict(form)
    return JSONResponse({"state": "success", "message": "Mission enregistrée avec succès."})

@app.post("/SinAuto_MCMA/gestion/GED/ajouterDocument")
async def mock_ged_ajouter(request: Request):
    form = await request.form()
    print(f"[MOCK API] /GED/ajouterDocument received: {dict(form)}")
    return JSONResponse({"state": "success", "message": "Document ajouté avec succès dans la GED."})

if __name__ == "__main__":
    print("==================================================================")
    print("[*] Starting MCMA Local Mock Simulation Server on http://127.0.0.1:8080")
    print("    Open in browser to see and test the interactive MCMA portal:")
    print("    -> http://127.0.0.1:8080/SinAuto_MCMA/expertise/gestionexpert/index")
    print("==================================================================")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")

