"""
run_dossier.py — Automatic MCMA Dossier Runner
===============================================
Picks up the dossier JSON from 'input_dossier/' and the 3 PDF documents
(Devis, Photos avant, Rapport) from 'input_documents/' automatically,
or accepts custom paths via CLI arguments.

Simple Usage (Zero config - reads input folders):
    python run_dossier.py

Advanced Usage (Custom paths):
    python run_dossier.py --json "input_dossier/custom.json" \
                          --devis "input_documents/devis.pdf" \
                          --photos "input_documents/photos_avant.pdf" \
                          --rapport "input_documents/rapport_expertise.pdf"
"""

import os
import sys
import glob
import json
import asyncio
import argparse
from mapper import WexiaToDossierMapper
from main import process_workflow

INPUT_DOSSIER_DIR = "input_dossier"
INPUT_DOCS_DIR = "input_documents"

def find_default_json() -> str:
    """Finds the first .json or .md dossier file in input_dossier/."""
    candidates = glob.glob(os.path.join(INPUT_DOSSIER_DIR, "*.json")) + \
                 glob.glob(os.path.join(INPUT_DOSSIER_DIR, "*.md"))
    return candidates[0] if candidates else ""

def find_documents_in_folder() -> list:
    """
    Scans input_documents/ and maps PDFs to their appropriate MCMA IdNatureDocument
    based on filename keywords.
    """
    pdf_files = glob.glob(os.path.join(INPUT_DOCS_DIR, "*.pdf"))
    docs = []

    for pdf in pdf_files:
        name_lower = os.path.basename(pdf).lower()
        
        if "devis" in name_lower or "quote" in name_lower:
            nature_id = "56"  # DEVIS DE REPARATION GARAGE
            label = "Devis de réparation"
        elif "photo" in name_lower or "avant" in name_lower or "degat" in name_lower or "damage" in name_lower:
            nature_id = "63"  # PHOTOS AVANT LA REPARATION
            label = "Photos avant réparation"
        elif "rapport" in name_lower or "expertise" in name_lower or "preliminaire" in name_lower:
            nature_id = "40"  # RAPPORT D'EXPERTISE PRELIMINAIRE DE REFORME / EXPERTISE
            label = "Rapport d'expertise"
        elif "carte" in name_lower or "grise" in name_lower:
            nature_id = "6"   # LA CARTE GRISE
            label = "Carte grise"
        elif "constat" in name_lower:
            nature_id = "22"  # CONSTAT AMIABLE
            label = "Constat amiable"
        else:
            nature_id = "74"  # AUTRE
            label = f"Document ({os.path.basename(pdf)})"

        docs.append({"path": os.path.abspath(pdf), "id_nature": nature_id, "label": label})

    return docs

def load_json_data(file_path: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        # Handle markdown-wrapped JSON (```json ... ```)
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines)
        return json.loads(content)

async def main():
    parser = argparse.ArgumentParser(description="MCMA Dossier Automation Runner")
    parser.add_argument("--json", default="", help="Path to dossier JSON (default: reads from input_dossier/)")
    parser.add_argument("--devis", help="Local PDF path for Devis (IdNature 56)")
    parser.add_argument("--photos", help="Local PDF path for Photos avant (IdNature 63)")
    parser.add_argument("--rapport", help="Local PDF path for Rapport (IdNature 40)")
    parser.add_argument("--reference", help="Override dossier reference search key")
    parser.add_argument("--matricule", "--immatriculation", dest="matricule", help="Override vehicle license plate / immatriculation search key")
    
    args = parser.parse_args()

    # Determine JSON file
    json_path = args.json or find_default_json()
    if not json_path or not os.path.exists(json_path):
        print(f"[!] Error: No dossier JSON found in '{INPUT_DOSSIER_DIR}/' or specified with --json.")
        print(f"[!] Please place your dossier JSON file inside the '{INPUT_DOSSIER_DIR}/' folder.")
        sys.exit(1)

    print(f"[*] Loading dossier JSON: {json_path}")
    raw_data = load_json_data(json_path)

    # Detect format & map fields
    if "dossier" in raw_data or "vehicule" in raw_data or "meta" in raw_data:
        print("[*] Detected Wexia schema format. Running mapper...")
        mapper = WexiaToDossierMapper()
        payload = mapper.map(raw_data)
    else:
        payload = raw_data

    # Overrides
    if args.reference:
        payload["dossier_reference"] = args.reference
    if args.matricule:
        payload["matricule"] = args.matricule

    # Resolve PDF documents: explicit CLI args first, or auto-detect from input_documents/
    local_docs = []
    if args.devis and os.path.exists(args.devis):
        local_docs.append({"path": os.path.abspath(args.devis), "id_nature": "56", "label": "Devis de réparation"})
    if args.photos and os.path.exists(args.photos):
        local_docs.append({"path": os.path.abspath(args.photos), "id_nature": "63", "label": "Photos avant réparation"})
    if args.rapport and os.path.exists(args.rapport):
        local_docs.append({"path": os.path.abspath(args.rapport), "id_nature": "40", "label": "Rapport préliminaire / expertise"})

    # If no explicit CLI PDF paths were passed, auto-scan input_documents/
    if not local_docs:
        local_docs = find_documents_in_folder()

    if local_docs:
        print(f"[*] Found {len(local_docs)} document(s) in '{INPUT_DOCS_DIR}/':")
        for d in local_docs:
            print(f"    • [{d['id_nature']}] {os.path.basename(d['path'])} ({d['label']})")
        payload["documents"] = local_docs
    else:
        print(f"[!] No PDFs found in '{INPUT_DOCS_DIR}/'. Proceeding without document upload.")

    print("\n" + "="*55)
    print(f"  Target Dossier Ref : {payload.get('dossier_reference')}")
    print(f"  Target Matricule   : {payload.get('matricule')}")
    print(f"  Rubriques count    : {len(payload.get('rubriques', []))}")
    print(f"  Documents count    : {len(payload.get('documents', []))}")
    print("="*55 + "\n")

    # Run browser automation
    result = await process_workflow(payload)
    print(f"[*] Execution Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
