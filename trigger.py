import requests

payload = {
    "dossier_reference": "3.20.02.2026.00233",
    "id_mission": "532805",
    "id_sinistre": "810692",
    "text_fields": {
        "NbreJourImmobilisation": "5",
        "Kilometrage": "45000",
        "ValeurVenale": "120000",
        "MontantReparation": "8500",
        "MontantTVA": "1700",
        "ObservationMission": "Test automatique via FastAPI agent."
    },
    "select_fields": {
        "PartResponsabilite": "100",
        "TypeReforme": "E"
    },
    "checkboxes": {
        "VehRepareI": True
    },
    "rubriques": [
        {
            "IdRubrique": "1",
            "MontantHT": "1500",
            "Taxe": "20"
        }
    ],
    "documents": [
        {
            "id_nature": "63",
            "path": "C:/Test_Files/avant.pdf"
        }
    ]
}

print("[*] Sending test JSON dossier payload to FastAPI agent...")
response = requests.post("http://127.0.0.1:8000/api/v1/fill-dossier", json=payload)

print("[*] Response received from Agent API:")
print(response.json())