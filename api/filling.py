"""
api/filling.py — Phase 2 Form Filling (DISABLED)
=================================================
Every endpoint that can drive the MCMA portal's expertise forms.

The whole router is gated behind the FORM_FILLING feature flag. It lives in its
own module precisely so that Phase 2 work cannot accidentally touch the Phase 1
operations hub, and so the disabled surface is visible in one place.

The one exception is /map-wexia-dossier: a pure, offline JSON transformation
that needs no browser and stays available.
"""

from fastapi import APIRouter, HTTPException

from api.schemas import FillDossierRequest, WexiaDossierRequest
from core.features import (
    FORM_FILLING_DISABLED_MESSAGE,
    FORM_FILLING_ENABLED,
    FeatureDisabledError,
)
from mapper.wexia_mapper import WexiaToDossierMapper
from workflows.fill_dossier import process_workflow

router = APIRouter(prefix="/api/v1", tags=["filling"])


def _require_enabled() -> None:
    if not FORM_FILLING_ENABLED:
        raise HTTPException(status_code=503, detail=FORM_FILLING_DISABLED_MESSAGE)


@router.post("/fill-dossier")
async def api_fill_dossier(req: FillDossierRequest):
    """Fills a dossier using the pre-mapped MCMA payload contract. DISABLED."""
    _require_enabled()
    try:
        result = await process_workflow(req.payload)
        return {"status": "success", "result": result}
    except FeatureDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fill-dossier-from-wexia")
async def api_fill_dossier_from_wexia(req: WexiaDossierRequest):
    """Translates raw Wexia JSON and executes MCMA filling. DISABLED."""
    _require_enabled()
    try:
        mapper = WexiaToDossierMapper()
        payload = mapper.map(req.wexia_payload, explicit_chiffrage_id=req.explicit_chiffrage_id)
        result = await process_workflow(payload)
        return {"status": "success", "result": result, "mapped_payload": payload}
    except FeatureDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/map-wexia-dossier")
async def api_map_wexia_dossier(req: WexiaDossierRequest):
    """
    Translates raw Wexia JSON into the MCMA payload contract WITHOUT a browser.
    Remains available while filling is disabled: pure and deterministic.
    """
    try:
        mapper = WexiaToDossierMapper()
        payload = mapper.map(req.wexia_payload, explicit_chiffrage_id=req.explicit_chiffrage_id)
        return {"status": "success", "mapped_payload": payload}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
