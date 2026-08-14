from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from playwright.async_api import async_playwright
from mapper import WexiaToDossierMapper
import fitz  # PyMuPDF
import os
import uuid

app = FastAPI(title="MCMA Dossier Automation API")

def compress_pdf(input_path: str, output_path: str) -> str:
    """Compresses heavy PDF files by cleaning streams and garbage collecting objects."""
    try:
        if not os.path.exists(input_path):
            print(f"[!] Warning: File not found: {input_path}")
            return input_path
        doc = fitz.open(input_path)
        doc.save(output_path, garbage=4, deflate=True, clean=True)
        doc.close()
        
        orig_size = os.path.getsize(input_path) / (1024 * 1024)
        new_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[PDF] Compressed {os.path.basename(input_path)}: {orig_size:.2f}MB -> {new_size:.2f}MB")
        return output_path
    except Exception as e:
        print(f"[PDF] Compression error: {e}")
        return input_path

# The payload model matches the structure of the incoming agency JSON file
class DossierPayload(BaseModel):
    dossier_reference: str = ""  # Extracted from JSON to search the dossier
    matricule: str = ""          # Alternative search key if needed
    text_fields: dict = {}
    select_fields: dict = {}
    checkboxes: dict = {}
    rubriques: list = []
    documents: list = []

async def process_workflow(data: dict):
    if not os.path.exists("mcma_auth_state.json"):
        return {"status": "error", "message": "mcma_auth_state.json missing. Run auth_setup.py first!"}

    os.makedirs("temp", exist_ok=True)

    async with async_playwright() as p:
        # Headless=False so you can visually watch the search and fill process
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="mcma_auth_state.json")
        page = await context.new_page()

        try:
            # --- STEP 1: GO TO SEARCH PAGE ---
            print(f"[*] Navigating to MCMA search/missions page...")
            await page.goto("https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/")
            await page.wait_for_load_state("domcontentloaded")

            # --- STEP 2: SEARCH USING VALUES FROM THE JSON FILE ---
            dossier_ref = data.get("dossier_reference")
            matricule = data.get("matricule")
            
            print(f"[*] Searching for dossier reference: {dossier_ref or matricule}...")
            
            if dossier_ref:
                await page.fill("#ReferenceCie", dossier_ref)
            if matricule:
                await page.fill("#Matricule", matricule)

            # Trigger the search action
            await page.click("a:has-text('Rechercher')")
            await page.wait_for_load_state("networkidle")

            # --- STEP 3: SELECT THE DOSSIER FROM SEARCH RESULTS ---
            print(f"[*] Selecting dossier from search results table...")
            mission_link = page.locator("a[title='Mission expertise']").first
            if await mission_link.count() > 0:
                await mission_link.click()
                await page.wait_for_load_state("domcontentloaded")
            else:
                raise Exception(f"Dossier '{dossier_ref}' not found in MCMA search results.")

            # --- STEP 4: FILL MAIN FORM TEXT FIELDS ---
            print(f"[*] Filling main form text fields...")
            for field_id, value in data.get("text_fields", {}).items():
                if value is not None and str(value).strip() != "":
                    selector = f"#{field_id}"
                    if await page.locator(selector).count() > 0:
                        await page.fill(selector, str(value))
                        print(f"    [✓] Filled text field #{field_id} = {str(value)[:40]}...")
                    else:
                        print(f"    [!] Field #{field_id} not present on page (skipped)")

            # --- STEP 5: SELECT DROPDOWN OPTIONS ---
            print(f"[*] Selecting dropdown options...")
            for field_id, value in data.get("select_fields", {}).items():
                if value is not None and str(value).strip() != "":
                    selector = f"#{field_id}"
                    if await page.locator(selector).count() > 0:
                        try:
                            await page.select_option(selector, str(value))
                            print(f"    [✓] Selected #{field_id} = {value}")
                        except Exception as e:
                            print(f"    [!] Option '{value}' in #{field_id} not found: {e} (skipped)")
                    else:
                        print(f"    [!] Dropdown #{field_id} not present on page (skipped)")

            # --- STEP 6: TOGGLE CHECKBOXES ---
            print(f"[*] Toggling checkboxes...")
            for field_id, is_checked in data.get("checkboxes", {}).items():
                selector = f"#{field_id}"
                if await page.locator(selector).count() > 0:
                    current_state = await page.locator(selector).is_checked()
                    if current_state != is_checked:
                        await page.click(selector)
                        await page.wait_for_timeout(200)
                        print(f"    [✓] Toggled checkbox #{field_id} -> {is_checked}")
                else:
                    print(f"    [!] Checkbox #{field_id} not present on page (skipped)")

            # --- STEP 7: INSERT LINE ITEMS (RUBRIQUES) ---
            rubriques = data.get("rubriques", [])
            if rubriques:
                print(f"[*] Adding {len(rubriques)} line item(s) (rubriques)...")
                for item in rubriques:
                    ajouter_btn = page.locator("a:has-text('Ajouter'), #btnAjouter, button:has-text('Ajouter')").first
                    if await ajouter_btn.count() > 0:
                        await ajouter_btn.click()
                        await page.wait_for_timeout(400)
                        
                        if await page.locator("#IdRubrique").count() > 0:
                            await page.select_option("#IdRubrique", str(item.get("IdRubrique")))
                        if await page.locator("#MontantHT").count() > 0:
                            await page.fill("#MontantHT", str(item.get("MontantHT", "0")))
                        if item.get("Taxe") and await page.locator("#Taxe").count() > 0:
                            await page.fill("#Taxe", str(item.get("Taxe")))
                        
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1000)

            # --- STEP 8: SAVE FORM BEFORE GED (as captured in spy script) ---
            print(f"[*] Saving mission form before GED...")
            save_mission_btn = page.locator("#Enregistrer, a:has-text('Enregistrer')").first
            if await save_mission_btn.count() > 0 and await save_mission_btn.is_visible():
                await save_mission_btn.click()
                await page.wait_for_timeout(1500)

            # --- STEP 9: OPEN GED PANEL & UPLOAD DOCUMENTS ---
            docs = data.get("documents", [])
            if docs:
                print(f"[*] Switching to GED panel for {len(docs)} document(s)...")
                ged_btn = page.locator("#loadGED, a:has-text('GED'), button:has-text('GED')").first
                if await ged_btn.count() > 0:
                    await ged_btn.click()
                    await page.wait_for_timeout(1000)
                
                for doc in docs:
                    file_path = doc.get("path")
                    id_nature = doc.get("id_nature")
                    
                    if not file_path or not os.path.exists(file_path):
                        print(f"[!] Warning: Document file not found on disk: {file_path}")
                        continue
                    
                    compressed_filename = f"temp/{uuid.uuid4()}_compressed.pdf"
                    final_file_path = compress_pdf(file_path, compressed_filename)
                    
                    print(f"[*] Uploading nature {id_nature} -> {os.path.basename(file_path)}...")
                    if await page.locator("#IdNatureDocument").count() > 0:
                        await page.select_option("#IdNatureDocument", str(id_nature))
                    
                    file_input = page.locator("input[type='file'][name='document'], #document, input[type='file']").first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(final_file_path)
                        await page.wait_for_timeout(400)
                        
                        # Click Enregistrer inside GED
                        enregistrer_ged = page.locator("#EnregistrerGED, #divGed a:has-text('Enregistrer'), #divGed button:has-text('Enregistrer'), a[onclick*='ajouterDocument']").first
                        if await enregistrer_ged.count() > 0:
                            await enregistrer_ged.click()
                            print(f"[✓] Document nature {id_nature} uploaded successfully.")
                            await page.wait_for_timeout(2500)
                        else:
                            print(f"[!] Could not locate GED Enregistrer button.")

            # --- STEP 10: HUMAN-IN-THE-LOOP REVIEW PAUSE ---
            print("\n" + "="*55)
            print(" [✓] AUTOMATION COMPLETE: Searched, filled form, & uploaded GED.")
            print(" [!] Review the dossier carefully on screen.")
            print(" [!] Click 'Resume' in Playwright Inspector or close when done.")
            print("="*55 + "\n")

            await page.pause()

            await browser.close()
            return {"status": "success", "message": "Dossier filled and reviewed successfully."}

        except Exception as e:
            await browser.close()
            return {"status": "failed", "error": str(e)}

@app.post("/api/v1/fill-dossier")
async def handle_dossier(payload: DossierPayload):
    result = await process_workflow(payload.model_dump())
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result

@app.post("/api/v1/fill-dossier-from-wexia")
async def handle_wexia_dossier(request: Request):
    """
    Accepts a full Wexia dossier JSON (format: wexia.dossier.full, schema_version 2.0),
    maps it to an MCMA-ready payload, downloads any document files from their signed
    URLs, then drives the browser automation exactly like /api/v1/fill-dossier.
    """
    try:
        wexia_json = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    # 1. Translate Wexia JSON -> flat MCMA payload
    mapper  = WexiaToDossierMapper(download_dir="temp")
    payload = mapper.map(wexia_json)

    print(f"[Wexia] Mapped dossier reference : {payload['dossier_reference']}")
    print(f"[Wexia] Mapped matricule         : {payload['matricule']}")
    print(f"[Wexia] Text fields              : {list(payload['text_fields'].keys())}")
    print(f"[Wexia] Select fields            : {list(payload['select_fields'].keys())}")
    print(f"[Wexia] Checkboxes               : {payload['checkboxes']}")
    print(f"[Wexia] Rubriques count          : {len(payload['rubriques'])}")
    print(f"[Wexia] Documents to download    : {len(payload['documents'])}")

    # 2. Download documents from signed URLs -> local temp files
    if payload["documents"]:
        payload["documents"] = await mapper.download_documents(payload["documents"])
        print(f"[Wexia] Documents downloaded     : {len(payload['documents'])}")

    # 3. Run the standard browser automation workflow
    result = await process_workflow(payload)
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000)