from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

import auth
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


class ProfileUpdate(BaseModel):
    kcal_goal: int = Field(ge=0, le=20000)
    protein_goal: float = Field(ge=0, le=2000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user_goals(conn, user_id: int) -> tuple[int, float]:
    row = conn.execute(
        "SELECT kcal_goal, protein_goal FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    return row["kcal_goal"], row["protein_goal"]


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


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
# Profile endpoints (per-user daily goals)
# ---------------------------------------------------------------------------
@app.get("/api/profile")
def get_profile(user=Depends(auth.get_current_user)):
    with get_connection() as conn:
        kcal_goal, protein_goal = _user_goals(conn, user["id"])
    return {
        "username": user["username"],
        "kcal_goal": kcal_goal,
        "protein_goal": protein_goal,
    }


@app.put("/api/profile")
def update_profile(body: ProfileUpdate, user=Depends(auth.get_current_user)):
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET kcal_goal = ?, protein_goal = ? WHERE id = ?",
            (body.kcal_goal, round(body.protein_goal, 1), user["id"]),
        )
    return {
        "kcal_goal": body.kcal_goal,
        "protein_goal": round(body.protein_goal, 1),
        "status": "updated",
    }


# ---------------------------------------------------------------------------
# Meal endpoints
# ---------------------------------------------------------------------------
@app.post("/api/meal/analyze")
async def meal_analyze(req: AnalyzeRequest, user=Depends(auth.get_current_user)):
    return await analyze_meal(req.text)


@app.post("/api/meal/save")
def meal_save(req: SaveRequest, user=Depends(auth.get_current_user)):
    """Persist each food item as its own row so they list individually."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Keine Items zum Speichern.")
    ids = []
    with get_connection() as conn:
        for it in req.items:
            cur = conn.execute(
                """
                INSERT INTO meals (user_id, raw_text, name, amount, kcal, protein)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user["id"], req.raw_text, it.name, it.amount, it.kcal, it.protein),
            )
            ids.append(cur.lastrowid)
    return {"ids": ids, "count": len(ids), "status": "saved"}


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
        kcal_goal, protein_goal = _user_goals(conn, user["id"])
        rows = conn.execute(
            """
            SELECT id, timestamp, raw_text, name, amount, kcal, protein
            FROM meals
            WHERE user_id = ? AND date(timestamp) = date('now')
            ORDER BY timestamp DESC
            """,
            (user["id"],),
        ).fetchall()

    items = [dict(r) for r in rows]
    total_kcal = sum(r["kcal"] or 0 for r in rows)
    total_protein = round(sum(r["protein"] or 0.0 for r in rows), 1)

    return {
        "date": today,
        "total_kcal": total_kcal,
        "total_protein": total_protein,
        "kcal_goal": kcal_goal,
        "protein_goal": protein_goal,
        "items": items,
    }


@app.get("/api/stats")
def stats(
    period: str = Query("week", pattern="^(week|month|all)$"),
    user=Depends(auth.get_current_user),
):
    """Aggregated totals + per-day breakdown for week / month / all-time."""
    where = "WHERE user_id = ?"
    params: list = [user["id"]]
    if period == "week":
        where += " AND date(timestamp) >= date('now', '-6 days')"
    elif period == "month":
        where += " AND date(timestamp) >= date('now', '-29 days')"

    with get_connection() as conn:
        kcal_goal, protein_goal = _user_goals(conn, user["id"])
        daily_rows = conn.execute(
            f"""
            SELECT date(timestamp) AS day,
                   SUM(kcal)    AS kcal,
                   SUM(protein) AS protein
            FROM meals
            {where}
            GROUP BY date(timestamp)
            ORDER BY day DESC
            """,
            params,
        ).fetchall()

    daily = [
        {
            "date": r["day"],
            "kcal": int(r["kcal"] or 0),
            "protein": round(r["protein"] or 0.0, 1),
        }
        for r in daily_rows
    ]
    total_kcal = sum(d["kcal"] for d in daily)
    total_protein = round(sum(d["protein"] for d in daily), 1)
    days_tracked = len(daily)
    avg_kcal = round(total_kcal / days_tracked) if days_tracked else 0
    avg_protein = round(total_protein / days_tracked, 1) if days_tracked else 0.0

    return {
        "period": period,
        "total_kcal": total_kcal,
        "total_protein": total_protein,
        "days_tracked": days_tracked,
        "avg_kcal": avg_kcal,
        "avg_protein": avg_protein,
        "kcal_goal": kcal_goal,
        "protein_goal": protein_goal,
        "daily": daily,
    }
