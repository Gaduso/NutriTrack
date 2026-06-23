# NutriTrack AI 🥗

Minimalistischer, mobil-optimierter Ernährungs-Tracker (PWA) für Kalorien & Protein.
KI-gestützte Freitext-Analyse via OpenRouter, gebaut mit FastAPI, gehostet auf Render.com.

## Features
- 📝 Freitext-Eingabe ("100g Nudeln mit 50g Faschiertem") → KI schätzt kcal & Protein
- ✏️ Werte vor dem Speichern editierbar (Vorschau-Tabelle)
- 📊 Tages-Dashboard mit Kalorien- und Protein-Zielen
- 🔐 JWT-Login (1 Jahr gültig), persistiert im `localStorage` — ideal für iOS-Homescreen-PWA
- 🌙 Modernes Slate-Dark-Mode-Design (Tailwind)

## Lokal starten
```bash
pip install -r requirements.txt
cp .env.example .env   # API-Key eintragen
uvicorn main:app --reload
```
Dann http://localhost:8000 öffnen.

## Deployment auf Render.com
Das mitgelieferte `render.yaml` (Blueprint) konfiguriert alles automatisch:
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Persistent Disk** unter `/data` (1 GB) für die SQLite-DB
- **Env Vars:** `OPENROUTER_API_KEY` (manuell setzen), `JWT_SECRET` (auto-generiert), `DATABASE_URL`

## Projektstruktur
```
main.py               FastAPI-App & API-Endpoints
auth.py               Registrierung, Login, JWT
database.py           SQLite-Schema & Verbindungen
openrouter_client.py  OpenRouter-HTTP-Client (httpx)
config.py             Konfiguration / Env-Variablen
templates/index.html  Frontend (PWA, Tailwind, Vanilla JS)
static/               manifest.json + Icons
render.yaml           Render.com Blueprint
```
