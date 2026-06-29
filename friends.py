"""Friend graph + viewing a friend's meals so couples can copy each other's food.

A friendship is a single row (requester_id, addressee_id) with a status of
``pending`` until the addressee accepts, then ``accepted``. Look-ups always
consider both directions so order does not matter once accepted.
"""

from fastapi import HTTPException

from database import get_connection


def _find_user(conn, username: str):
    return conn.execute(
        "SELECT id, username FROM users WHERE lower(username) = lower(%s)",
        (username,),
    ).fetchone()


def send_request(user_id: int, username: str) -> dict:
    username = (username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Benutzername erforderlich.")
    with get_connection() as conn:
        target = _find_user(conn, username)
        if not target:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
        if target["id"] == user_id:
            raise HTTPException(status_code=400, detail="Du kannst dich nicht selbst hinzufügen.")

        existing = conn.execute(
            """
            SELECT id, status, requester_id FROM friendships
            WHERE (requester_id = %s AND addressee_id = %s)
               OR (requester_id = %s AND addressee_id = %s)
            """,
            (user_id, target["id"], target["id"], user_id),
        ).fetchone()
        if existing:
            if existing["status"] == "accepted":
                raise HTTPException(status_code=409, detail="Ihr seid bereits befreundet.")
            if existing["requester_id"] == user_id:
                raise HTTPException(status_code=409, detail="Anfrage bereits gesendet.")
            # The other person already invited us — accept instead of duplicating.
            conn.execute(
                "UPDATE friendships SET status = 'accepted' WHERE id = %s", (existing["id"],)
            )
            return {"status": "accepted", "username": target["username"]}

        conn.execute(
            "INSERT INTO friendships (requester_id, addressee_id, status) VALUES (%s, %s, 'pending')",
            (user_id, target["id"]),
        )
    return {"status": "pending", "username": target["username"]}


def respond_request(user_id: int, req_id: int, accept: bool) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, addressee_id, status FROM friendships WHERE id = %s", (req_id,)
        ).fetchone()
        if not row or row["addressee_id"] != user_id or row["status"] != "pending":
            raise HTTPException(status_code=404, detail="Anfrage nicht gefunden.")
        if accept:
            conn.execute("UPDATE friendships SET status = 'accepted' WHERE id = %s", (req_id,))
        else:
            conn.execute("DELETE FROM friendships WHERE id = %s", (req_id,))
    return {"status": "accepted" if accept else "declined"}


def remove_friend(user_id: int, friend_id: int) -> dict:
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM friendships
            WHERE (requester_id = %s AND addressee_id = %s)
               OR (requester_id = %s AND addressee_id = %s)
            """,
            (user_id, friend_id, friend_id, user_id),
        )
    return {"status": "removed"}


def list_friends(user_id: int) -> dict:
    with get_connection() as conn:
        friends = conn.execute(
            """
            SELECT u.id, u.username
            FROM friendships f
            JOIN users u
              ON u.id = CASE WHEN f.requester_id = %s THEN f.addressee_id ELSE f.requester_id END
            WHERE f.status = 'accepted' AND (f.requester_id = %s OR f.addressee_id = %s)
            ORDER BY lower(u.username)
            """,
            (user_id, user_id, user_id),
        ).fetchall()
        incoming = conn.execute(
            """
            SELECT f.id, u.username
            FROM friendships f JOIN users u ON u.id = f.requester_id
            WHERE f.status = 'pending' AND f.addressee_id = %s
            ORDER BY f.created_at
            """,
            (user_id,),
        ).fetchall()
        outgoing = conn.execute(
            """
            SELECT f.id, u.username
            FROM friendships f JOIN users u ON u.id = f.addressee_id
            WHERE f.status = 'pending' AND f.requester_id = %s
            ORDER BY f.created_at
            """,
            (user_id,),
        ).fetchall()
    return {
        "friends": [dict(r) for r in friends],
        "incoming": [dict(r) for r in incoming],
        "outgoing": [dict(r) for r in outgoing],
    }


def _are_friends(conn, a: int, b: int) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM friendships
        WHERE status = 'accepted'
          AND ((requester_id = %s AND addressee_id = %s)
            OR (requester_id = %s AND addressee_id = %s))
        """,
        (a, b, b, a),
    ).fetchone() is not None


def friend_meals(user_id: int, friend_id: int, tz: str) -> dict:
    """Today's meals of a friend, so the caller can copy parts into their own log."""
    with get_connection() as conn:
        if not _are_friends(conn, user_id, friend_id):
            raise HTTPException(status_code=403, detail="Ihr seid nicht befreundet.")
        friend = conn.execute(
            "SELECT username FROM users WHERE id = %s", (friend_id,)
        ).fetchone()
        rows = conn.execute(
            """
            SELECT id, timestamp, name, amount, kcal, protein, meal_type
            FROM meals
            WHERE user_id = %s
              AND (timestamp AT TIME ZONE %s)::date = (now() AT TIME ZONE %s)::date
            ORDER BY timestamp DESC
            """,
            (friend_id, tz, tz),
        ).fetchall()
    return {
        "username": friend["username"] if friend else "",
        "items": [dict(r) for r in rows],
    }
