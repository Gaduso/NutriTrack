# NutriTrack AI 🥗

Minimalistischer, mobil-optimierter Ernährungs-Tracker (PWA) für Kalorien & Protein.
KI-gestützte Freitext-Analyse via OpenRouter, gebaut mit FastAPI + PostgreSQL,
gehostet auf Render.com.

## Features
- 📝 Freitext-Eingabe ("100g Nudeln mit 50g Faschiertem") → KI schätzt kcal & Protein
- ✏️ Werte vor dem Speichern editierbar (Vorschau-Tabelle)
- ⌨️ Manuelle Einträge ohne KI (Name, Menge, kcal, Protein)
- 🍽️ Kategorisierung nach Frühstück / Mittag / Abend / Snack — mit smartem
  Standard nach Tageszeit; „Heute" ist nach Kategorie gruppiert inkl. Subtotale
- 📊 Tages-Dashboard mit persönlichen Kalorien- & Protein-Zielen
- 📈 Übersicht für Woche / Monat / Gesamt (Σ + Ø pro Tag)
- 🔐 JWT-Login (1 Jahr gültig), persistiert im `localStorage` — ideal für iOS-Homescreen-PWA
- 🌙 Modernes Slate-Dark-Mode-Design (Tailwind), iOS Safe-Area-Support

## Lokal starten
```bash
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL + OPENROUTER_API_KEY eintragen
uvicorn main:app --reload
```
Benötigt eine erreichbare PostgreSQL-Datenbank (`DATABASE_URL`). Dann
http://localhost:8000 öffnen.

## Deployment auf Render.com
`render.yaml` (Blueprint) konfiguriert den Web-Service:
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Env Vars (im Dashboard setzen):**
  - `DATABASE_URL` — Internal Connection URL der PostgreSQL-Instanz
  - `OPENROUTER_API_KEY` — OpenRouter-Key
  - `JWT_SECRET` — wird von Render automatisch generiert

Die Tabellen werden beim Start automatisch erstellt (`init_db()`), inklusive
additiver Migrationen — kein manueller Migrationsschritt nötig.

## Projektstruktur
```
main.py               FastAPI-App & API-Endpoints
auth.py               Registrierung, Login, JWT
database.py           PostgreSQL-Schema & Verbindungen (psycopg)
openrouter_client.py  OpenRouter-HTTP-Client (httpx)
config.py             Konfiguration / Env-Variablen
templates/index.html  Frontend (PWA, Tailwind, Vanilla JS)
static/               manifest.json + Icons
render.yaml           Render.com Blueprint
```
