import json
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

import auth
from config import settings
from database import get_connection, init_db
from openrouter_client import analyze_meal

app = FastAPI(title="NutriTrack AI")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1)


class MealItem(BaseModel):
    name: str
    amount: str = ""
    kcal: int = 0
    protein: float = 0.0


class SaveRequest(BaseModel):
    raw_text: str = ""
    items: list[MealItem] = []
    total_kcal: int = 0
    total_protein: float = 0.0


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "kcal_goal": settings.DAILY_KCAL_GOAL,
            "protein_goal": settings.DAILY_PROTEIN_GOAL,
        },
    )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.post("/api/register")
def register(creds: Credentials):
    return auth.register_user(creds.username, creds.password)


@app.post("/api/login")
def login(creds: Credentials):
    return auth.authenticate_user(creds.username, creds.password)


# ---------------------------------------------------------------------------
# Meal endpoints
# ---------------------------------------------------------------------------
@app.post("/api/meal/analyze")
async def meal_analyze(req: AnalyzeRequest, user=Depends(auth.get_current_user)):
    return await analyze_meal(req.text)


@app.post("/api/meal/save")
def meal_save(req: SaveRequest, user=Depends(auth.get_current_user)):
    json_data = json.dumps(
        {
            "items": [i.model_dump() for i in req.items],
            "total_kcal": req.total_kcal,
            "total_protein": req.total_protein,
        },
        ensure_ascii=False,
    )
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO meals (user_id, raw_text, json_data, total_kcal, total_protein)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], req.raw_text, json_data, req.total_kcal, req.total_protein),
        )
        meal_id = cur.lastrowid
    return {"id": meal_id, "status": "saved"}


@app.delete("/api/meal/{meal_id}")
def meal_delete(meal_id: int, user=Depends(auth.get_current_user)):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM meals WHERE id = ? AND user_id = ?", (meal_id, user["id"])
        )
    return {"status": "deleted"}


@app.get("/api/dashboard")
def dashboard(user=Depends(auth.get_current_user)):
    today = datetime.now(timezone.utc).date().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, raw_text, json_data, total_kcal, total_protein
            FROM meals
            WHERE user_id = ? AND date(timestamp) = date('now')
            ORDER BY timestamp DESC
            """,
            (user["id"],),
        ).fetchall()

    meals = []
    total_kcal = 0
    total_protein = 0.0
    for r in rows:
        try:
            items = json.loads(r["json_data"]).get("items", [])
        except (TypeError, json.JSONDecodeError):
            items = []
        total_kcal += r["total_kcal"] or 0
        total_protein += r["total_protein"] or 0.0
        meals.append(
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "raw_text": r["raw_text"],
                "items": items,
                "total_kcal": r["total_kcal"],
                "total_protein": r["total_protein"],
            }
        )

    return {
        "date": today,
        "total_kcal": total_kcal,
        "total_protein": round(total_protein, 1),
        "kcal_goal": settings.DAILY_KCAL_GOAL,
        "protein_goal": settings.DAILY_PROTEIN_GOAL,
        "meals": meals,
    }
