from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

import auth
import friends
from database import MEAL_TYPES, get_connection, init_db
from openfoodfacts import lookup_product
from openrouter_client import analyze_meal, analyze_meal_image

app = FastAPI(title="NutriTrack AI")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

MealType = Literal["breakfast", "lunch", "dinner", "snack"]


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(Credentials):
    # Invite secret gatekeeping sign-ups (validated server-side).
    secret: str = ""


class FriendRequest(BaseModel):
    username: str = Field(min_length=1)


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1)


class ImageRequest(BaseModel):
    # Base64 data URL, e.g. "data:image/jpeg;base64,...."
    image: str = Field(min_length=1)


class MealItem(BaseModel):
    name: str = Field(min_length=1)
    amount: str = ""
    kcal: int = 0
    protein: float = 0.0


class SaveRequest(BaseModel):
    raw_text: str = ""
    meal_type: MealType = "snack"
    items: list[MealItem] = []


class ProfileUpdate(BaseModel):
    kcal_goal: int = Field(ge=0, le=20000)
    protein_goal: float = Field(ge=0, le=2000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_tz(tz: str) -> str:
    """Return a valid IANA timezone name, falling back to UTC for bad input.

    Used so days are bucketed by the user's local timezone, not the server's UTC.
    """
    tz = (tz or "").strip()
    if not tz:
        return "UTC"
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        return "UTC"


def _user_goals(conn, user_id: int) -> tuple[int, float]:
    row = conn.execute(
        "SELECT kcal_goal, protein_goal FROM users WHERE id = %s", (user_id,)
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
def register(creds: RegisterRequest):
    return auth.register_user(creds.username, creds.password, creds.secret)


@app.post("/api/login")
def login(creds: Credentials):
    return auth.authenticate_user(creds.username, creds.password)


# ---------------------------------------------------------------------------
# Friends endpoints (send/accept requests, list friends, view their meals)
# ---------------------------------------------------------------------------
@app.get("/api/friends")
def friends_list(user=Depends(auth.get_current_user)):
    return friends.list_friends(user["id"])


@app.post("/api/friends/request")
def friends_request(body: FriendRequest, user=Depends(auth.get_current_user)):
    return friends.send_request(user["id"], body.username)


@app.post("/api/friends/{req_id}/accept")
def friends_accept(req_id: int, user=Depends(auth.get_current_user)):
    return friends.respond_request(user["id"], req_id, accept=True)


@app.post("/api/friends/{req_id}/decline")
def friends_decline(req_id: int, user=Depends(auth.get_current_user)):
    return friends.respond_request(user["id"], req_id, accept=False)


@app.delete("/api/friends/{friend_id}")
def friends_remove(friend_id: int, user=Depends(auth.get_current_user)):
    return friends.remove_friend(user["id"], friend_id)


@app.get("/api/friends/{friend_id}/meals")
def friends_meals(
    friend_id: int, tz: str = Query("UTC"), user=Depends(auth.get_current_user)
):
    return friends.friend_meals(user["id"], friend_id, _safe_tz(tz))


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
            "UPDATE users SET kcal_goal = %s, protein_goal = %s WHERE id = %s",
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


@app.post("/api/meal/analyze-image")
async def meal_analyze_image(req: ImageRequest, user=Depends(auth.get_current_user)):
    if not req.image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Ungültiges Bildformat (Data-URL erwartet).")
    # ~6 MB base64 cap to keep payloads sane on the free tier.
    if len(req.image) > 8_000_000:
        raise HTTPException(status_code=413, detail="Bild zu groß. Bitte kleiner aufnehmen.")
    return await analyze_meal_image(req.image)


@app.get("/api/product/{barcode}")
async def product_lookup(barcode: str, user=Depends(auth.get_current_user)):
    return await lookup_product(barcode)


@app.post("/api/meal/save")
def meal_save(req: SaveRequest, user=Depends(auth.get_current_user)):
    """Persist each food item as its own row (AI result or a manual entry)."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Keine Items zum Speichern.")
    ids = []
    with get_connection() as conn:
        for it in req.items:
            row = conn.execute(
                """
                INSERT INTO meals (user_id, raw_text, name, amount, kcal, protein, meal_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user["id"],
                    req.raw_text,
                    it.name,
                    it.amount,
                    it.kcal,
                    it.protein,
                    req.meal_type,
                ),
            ).fetchone()
            ids.append(row["id"])
    return {"ids": ids, "count": len(ids), "status": "saved"}


@app.delete("/api/meal/{meal_id}")
def meal_delete(meal_id: int, user=Depends(auth.get_current_user)):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM meals WHERE id = %s AND user_id = %s", (meal_id, user["id"])
        )
    return {"status": "deleted"}


@app.get("/api/dashboard")
def dashboard(tz: str = Query("UTC"), user=Depends(auth.get_current_user)):
    tz = _safe_tz(tz)
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    with get_connection() as conn:
        kcal_goal, protein_goal = _user_goals(conn, user["id"])
        rows = conn.execute(
            """
            SELECT id, timestamp, raw_text, name, amount, kcal, protein, meal_type
            FROM meals
            WHERE user_id = %s
              AND (timestamp AT TIME ZONE %s)::date = (now() AT TIME ZONE %s)::date
            ORDER BY timestamp DESC
            """,
            (user["id"], tz, tz),
        ).fetchall()

    items = [dict(r) for r in rows]
    total_kcal = sum(r["kcal"] or 0 for r in rows)
    total_protein = round(sum(r["protein"] or 0.0 for r in rows), 1)

    # Subtotals per meal category (always include all keys so the UI is stable).
    by_type = {mt: {"kcal": 0, "protein": 0.0, "count": 0} for mt in MEAL_TYPES}
    for r in rows:
        b = by_type[r["meal_type"]] if r["meal_type"] in by_type else by_type["snack"]
        b["kcal"] += r["kcal"] or 0
        b["protein"] = round(b["protein"] + (r["protein"] or 0.0), 1)
        b["count"] += 1

    return {
        "date": today,
        "total_kcal": total_kcal,
        "total_protein": total_protein,
        "kcal_goal": kcal_goal,
        "protein_goal": protein_goal,
        "by_type": by_type,
        "items": items,
    }


@app.get("/api/stats")
def stats(
    period: str = Query("week", pattern="^(week|month|all)$"),
    tz: str = Query("UTC"),
    user=Depends(auth.get_current_user),
):
    """Aggregated totals + per-day breakdown for week / month / all-time.

    Days are bucketed by the user's local timezone (``tz``), not UTC.
    """
    tz = _safe_tz(tz)
    day_expr = "(timestamp AT TIME ZONE %s)::date"

    # Parameter order must match the %s occurrences below.
    # GROUP BY / ORDER BY reference the output alias "day" so the tz parameter
    # only appears in SELECT (and the optional period filter).
    params: list = [tz, user["id"]]  # SELECT day_expr, then WHERE user_id
    period_clause = ""
    if period == "week":
        period_clause = f" AND {day_expr} >= (now() AT TIME ZONE %s)::date - INTERVAL '6 days'"
        params += [tz, tz]
    elif period == "month":
        period_clause = f" AND {day_expr} >= (now() AT TIME ZONE %s)::date - INTERVAL '29 days'"
        params += [tz, tz]

    with get_connection() as conn:
        kcal_goal, protein_goal = _user_goals(conn, user["id"])
        daily_rows = conn.execute(
            f"""
            SELECT {day_expr} AS day,
                   SUM(kcal)    AS kcal,
                   SUM(protein) AS protein
            FROM meals
            WHERE user_id = %s{period_clause}
            GROUP BY day
            ORDER BY day DESC
            """,
            params,
        ).fetchall()

    daily = [
        {
            "date": r["day"].isoformat(),
            "kcal": int(r["kcal"] or 0),
            "protein": round(float(r["protein"] or 0.0), 1),
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
