# RackKit FarmOS

Self-hosted production control for the RackKit 3D-printing farm. FarmOS is built around a **print queue**, not hobby printer monitoring: production jobs, G-code reuse, bed-clear confirmation, QC, finished-part inventory, filament costing, BOMs, and WooCommerce orders.

## Stack

- Next.js + React + TypeScript + Tailwind CSS (shop-floor UI)
- FastAPI + SQLAlchemy + Alembic
- PostgreSQL
- Redis (scheduler lock and future job fan-out)
- Docker Compose

## Fresh install

```bash
git clone <this-repo> rackkit-farmos
cd rackkit-farmos
cp .env.example .env
# set SECRET_KEY to a long random string
docker compose up -d
```

Open http://localhost:3000

1. Complete the first-run setup wizard (admin account).
2. Load demo data if you want a simulated Flex Rack 5 farm immediately.
3. Add real printers (OctoPrint, Moonraker/Klipper, Creality K1/K2) when ready.

The API is on http://localhost:8000 (`/docs` for OpenAPI).

## What the queue does

- Create a production run with multiple G-code files and copy counts.
- Restrict which printers may take that run.
- The scheduler assigns queued jobs to compatible **idle** printers.
- When a print finishes, the printer is **Waiting for Bed Clear**. Nothing else starts on that machine until an operator confirms the bed is empty. FarmOS does not assume automatic part ejection.
- Pause, resume, reorder, cancel, and move jobs between printers.
- Job history is permanent (status changes, never deleted).
- Filenames such as `RK-FR5-Handle-x4.gcode` produce four handles per print.

Printed parts go **Printed → Awaiting QC → Passed / Failed**. Only passed parts become sellable inventory. Failed parts are scrap and can be requeued.

## Printer adapters

New hardware is an adapter class, not an application rewrite:

| Adapter | Use |
| --- | --- |
| `octoprint` | OctoPrint hosts, including CR-6 Max |
| `moonraker` | Klipper via Moonraker |
| `creality` | K1 Max / K2 Pro (Moonraker, with Creality HTTP fallback) |
| `simulated` | Development and shop-floor demos |

API keys are encrypted at rest and **never** returned to the browser.

## WooCommerce

Set in `.env` (never hard-code):

```
WOOCOMMERCE_URL=https://your-shop.example
WOOCOMMERCE_KEY=ck_...
WOOCOMMERCE_SECRET=cs_...
```

Webhook: `POST /api/v1/woocommerce/webhook`  
Manual pull: Orders page → Sync WooCommerce.

Imported orders explode the product BOM, reserve finished parts, and queue production for the remainder.

## Environment

See `.env.example`. Important keys:

- `SECRET_KEY` — JWT and credential encryption
- `POSTGRES_PASSWORD`
- `SIMULATED_TIME_SCALE` — demo printers run faster than wall clock
- WooCommerce and SMTP / `NOTIFY_WEBHOOK_URL` as needed

## Backups

```bash
./scripts/backup.sh
```

Writes a gzipped `pg_dump` under `./backups/`. Keep the `uploads` Docker volume as well (G-code library).

## Local development (without Docker)

PostgreSQL and Redis must be running.

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://farmos:farmos@127.0.0.1:5432/farmos
alembic upgrade head
uvicorn app.main:app --reload --port 8472

# frontend
cd frontend
npm install
API_INTERNAL_URL=http://127.0.0.1:8472 npm run dev -- --port 43123 --hostname 0.0.0.0
```

## Security notes

- Password hashing: bcrypt
- JWT session tokens
- Role-ready (`admin`, `operator`, `viewer`) — admin bypasses role gates; extend `require_roles` as you add users
- Input validation via Pydantic
- Printer secrets encrypted; omitted from API responses
- Database migrations via Alembic (`create_all` also runs on boot for first install)
- Structured logging on the API and scheduler

## License

Private / internal RackKit tooling unless you add a license file.
