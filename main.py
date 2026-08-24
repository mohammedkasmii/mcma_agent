"""HTTP planning API for the modular MCMA agent.

Interactive browser filling intentionally remains a CLI operation because an
operator must see and review the company browser. The API validates incoming
JSON and returns the deterministic fill plan; it cannot save, validate, close,
or upload anything to MCMA.
"""

from typing import Any

from fastapi import FastAPI, HTTPException

from mcma.mapping.wexia import MappingError, WexiaDossierMapper
from mcma.planning.form import FormPlanner


app = FastAPI(title="MCMA Dossier Planning API", version="2.0.0")
mapper = WexiaDossierMapper()
planner = FormPlanner()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/plan-dossier")
async def plan_dossier(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        plan = planner.build(mapper.map(payload))
    except MappingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = plan.dossier.to_public_dict()
    result["operation_count"] = len(plan.fields)
    result["capabilities"] = {
        "form_fill": True,
        "draft_rubriques": True,
        "ged": False,
        "mission_save": False,
        "final_validation": False,
        "closure": False,
    }
    return result


@app.post("/api/v1/fill-dossier", status_code=409)
async def fill_dossier_requires_operator() -> None:
    raise HTTPException(
        status_code=409,
        detail=(
            "Interactive MCMA filling requires an operator-visible browser. "
            "Use run_dossier.py with a JSON file after requesting /api/v1/plan-dossier."
        ),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000)
