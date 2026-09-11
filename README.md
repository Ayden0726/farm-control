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
- Phone push: `NTFY_*`, `PUBLIC_APP_URL`, optional Pushover / Discord / Telegram / Twilio

## Phone notifications

FarmOS sends push notifications through a provider adapter layer. **ntfy** is the default easy option (self-hosted or ntfy.sh). Pushover, Discord, Telegram, email, Twilio SMS, and generic webhooks are also implemented and can be turned on from **Settings**.

Do not put API keys in source. Configure them in `.env` or paste them on the Settings page (encrypted at rest, never returned to the browser).

1. Install the [ntfy](https://ntfy.sh) app and subscribe to a private topic.
2. Open FarmOS → Settings → Phone notifications.
3. Set **Public FarmOS URL** to the address a phone can actually open (not `localhost` on a real shop network).
4. Enter the ntfy server + topic, enable the provider, and tap **Send test**.
5. Choose which events notify (print complete, print failed, bed clear, offline, filament low, production complete, order ready, maintenance due).
6. Optionally override those toggles per printer.

A completed print looks like:

```
K1 Max 02 — Print Complete

RK-FR5-Handle-x4 has finished printing.

Production Run: Flex Rack 5 — Batch 004
Quantity: 4
Status: Waiting for Bed Clear
Duration: 42m 0s
Completed: 2026-09-10 21:04 UTC

Open RackKit FarmOS to clear the bed and start the next queued job.
```

The notification includes a button/link into that printer so the operator can confirm bed clear. Delivery history (time, event, printer, job, provider, sent/failed) lives under **Notifications**. Failed sends are logged there instead of being dropped.

## Filament inventory and FarmOS barcodes

Manufacturer barcodes are **not** used. FarmOS generates its own codes, and filament information is entered **once** as a reusable **filament profile**:

- **Filament profile** (`FILT-SID-PETG-BLACK-3KG`) — manufacturer, product, material, colour, spool size, supplier, normal cost, temperatures, and reorder settings. Print this barcode for the shelf or receiving bench.
- **Physical spool** (`SPOOL-000142`) — one actual roll. Sequential numbers come from a locked database sequence and are never reused, including after a roll is emptied or archived.

Workflow: create the profile once → later open that profile (or scan its FILT- barcode) → **Add New Rolls** → quantity, optional price, location → **Create Rolls**. FarmOS allocates the next SPOOL numbers and offers **Print All** / **Print Selected** (one per page, adhesive sheets, or a label printer). **Reprint Label** on an existing spool regenerates the same QR and number; it does not create a new roll.

Each spool keeps the purchase price paid when it arrived, even if the profile’s normal price changes later.

Purchase orders can be received from the PO itself without scanning. Reorder modes: Off, Suggest only, **Create purchase order** (default), Approve and order, Full auto (architected, **disabled** unless spending controls explicitly enable it). Available stock = physical − committed (queue, current prints, production runs, waiting orders).

Phone **SCAN** uses the camera (QR and Code 128) with manual entry as fallback. Scanning a profile barcode opens **Add New Rolls**. Add FarmOS to the home screen as a PWA.

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
API_INTERNAL_URL=http://127.0.0.1:8472 npm run dev
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
