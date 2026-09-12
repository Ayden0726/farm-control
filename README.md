# Print FarmOS

Self-hosted production control for a 3D-printing farm. Print FarmOS is built around a **print queue**, not hobby printer monitoring: production jobs, G-code reuse, bed-clear confirmation, QC, finished-part inventory, filament costing, BOMs, and WooCommerce orders.

## Stack

- Next.js + React + TypeScript + Tailwind CSS (shop-floor UI)
- FastAPI + SQLAlchemy + Alembic
- PostgreSQL
- Redis (scheduler lock and future job fan-out)
- Docker Compose

## Fresh install

On a Linux server or WSL:

```bash
git clone https://github.com/Ayden0726/farm-control.git
cd farm-control
./install.sh
```

On Windows with Docker Desktop:

```powershell
git clone https://github.com/Ayden0726/farm-control.git
cd farm-control
.\install.ps1
```

The GitHub repo is private, so Git will ask you to sign in. Use a [personal access token](https://github.com/settings/tokens) as the password (`repo` scope).

The script installs Docker if needed (Linux), writes `.env` with random secrets, and starts the stack. Open the URL it prints (usually `http://YOUR_SERVER_IP:3000`). First visit should land on `/setup`.

1. Complete the first-run setup wizard (admin account).
2. Uncheck **Load demo data** for a live shop. Leave it checked for a simulated farm.
3. Add real printers (OctoPrint, Moonraker/Klipper, Creality K1/K2) when ready.

If the wizard does not appear, login fails, or backend logs say **password authentication failed**, leftover Docker volumes still have an old database password. Reset shop data (this wipes Postgres) and start again:

```bash
./install.sh --reset
```

Windows: `.\install.ps1 -Reset`

If phones or other PCs will use a specific address:

```bash
./install.sh --host http://192.168.1.50:3000
```

## Update

In the app: **Settings → Update Print FarmOS**.

The first time (or after a reboot if the updater is not installed as a service), run this once on the server so the button can work:

```bash
./update.sh
```

Windows with Docker Desktop: `.\update.ps1`

That pulls the latest code and rebuilds containers. Postgres data and uploaded G-code are kept.

The API is on port 8000 (`/docs` for OpenAPI).

## What the queue does

- Create a production run with multiple G-code files and copy counts. **Add from Products / BOM** explodes a catalog product onto the run: every required printed part, and every non-archived G-code tagged to that part. Hardware BOM lines are skipped. Optional accessories stay off unless you check the box. You can do the same on an existing run with **Add product from catalog**.
- Restrict which printers may take that run.
- The scheduler assigns queued jobs to compatible **idle** printers.
- When a print finishes, the printer is **Waiting for Bed Clear**. Nothing else starts on that machine until an operator confirms the bed is empty.
- **Settings → Automation** has **Assume the printer removes finished parts**, **off by default**. Print FarmOS does not command the print head to knock a part off. Turn this on only if the machine already clears the bed (belt printer, knock-off macro, etc.). Successful prints then go idle and the next job can start. Failed and cancelled prints still wait for bed clear.
- The queue runs **G-code**, not STLs. Print FarmOS is not a slicer and cannot pack copies onto a plate or write G-code. Upload an STL to get a **grid estimate** (bounding box vs the plate size in Settings). Pack the real plate in OrcaSlicer or PrusaSlicer, then upload that G-code. A filename with a number plus `pcs` (`Handle-4pcs.gcode`, `RK-FR5-Handle-4pcs.gcode`) sets **quantity** to that many of this part on the plate. `x` plus a number (`RK-FR5-Handle-x4.gcode`, `Bracket-x4-PETG.gcode`) still works. You can still change quantity on the upload form or in the library. Print time and filament grams come from slicer **header and footer** comments (Cura, Prusa, Orca, Bambu, ideaMaker). Filenames with `2h15m` or `48g` (or similar) also set print time and filament grams when those comments are missing. Use **Library → Re-read estimates** to refresh files already on disk without re-uploading.
- Pause, resume, reorder, cancel, and move jobs between printers.
- Delete a production run from the list or the run page. Queued work is cancelled. Job history stays (unlinked). FarmOS refuses the delete while a plate from that run is still on a printer.
- Job history is permanent (status changes, never deleted).

Printed parts go **Printed → Awaiting QC → Passed / Failed / Partial**. Only passed parts become sellable inventory. Failed parts are scrap. If **Automatically requeue failed QC parts** is on (Settings → Manufacturing), FarmOS reprints only the failed quantity.

## Manufacturing (FarmOS MES)

FarmOS plans production from open orders, BOMs, reserved inventory, the print queue, printer compatibility, filament, and maintenance status.

1. A WooCommerce (or manual) order explodes the product BOM and **reserves** available finished parts. Available = physical − reserved.
2. **Planner** shows a month/week calendar of needed-by dates. Pick a day, auto-select compatible printers, add G-code or explode a catalog product, then **Schedule** onto the queue. **Generate production plan** still calculates true shortages and recommends compatible printers; **Commit to print queue** keeps that needed-by date. Jobs enqueue now; earlier due dates print first among queued work.
3. **Recommended next jobs** on the dashboard queues work by order age, stock shortages, compatibility, and filament.
4. Prints complete into QC. Failed quantities become scrap and optional replacement jobs.
5. Passed parts land in finished-part **bins**. Scan a `BIN-` QR to open the bin.
6. When all printed and purchased BOM lines are available, **Kitting** shows **Kit Ready**. Reserve into a `KIT-` batch.
7. **Packing station** confirms every line (or override, which is audited) then **Ready to ship**. Scan an `ORDER-` QR to open packing.
8. Record carrier + tracking. WooCommerce is updated when that integration is configured.

Hardware, packaging, and consumables share the filament purchase-order approval modes. Costing uses filament price, optional electricity ($/kWh × printer watts × hours), failure allowance, machine time, and hardware. Compatibility checks (nozzle, material, bed) block automatic assignment unless an administrator overrides.

Global **SCAN** routes `PRINTER-`, `SPOOL-`, `FILT-`, `BIN-`, `ORDER-`, `BATCH-`, `KIT-`, and `HW-` codes. Search covers the same objects from desktop.

## Printer adapters

New hardware is an adapter class, not an application rewrite:

| Adapter | Use |
| --- | --- |
| `octoprint` | OctoPrint hosts, including CR-6 Max |
| `moonraker` | Klipper via Moonraker |
| `creality` | K1 Max / K2 Pro (Moonraker, with Creality HTTP fallback) |
| `simulated` | Development and shop-floor demos |

API keys are encrypted at rest and **never** returned to the browser.

Use **http://PRINTER_LAN_IP** (OctoPrint is usually port 80). FarmOS does not require TLS certificates on the printer and ignores self-signed HTTPS if the box redirects. OctoPrint **HTTP 409** while adding a printer means OctoPrint is up but the machine is not connected in OctoPrint (USB/serial). That is not a certificate error — connect the printer in the OctoPrint UI, or save anyway; FarmOS will keep it offline until it is connected.

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

## Shopify

Use Shopify instead of WooCommerce, or run both shops at once. Set in `.env` (never hard-code), or save the shop and token in **Settings** (encrypted at rest):

```
SHOPIFY_SHOP=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_...
SHOPIFY_WEBHOOK_SECRET=
SHOPIFY_API_VERSION=2024-10
```

`SHOPIFY_SHOP` can be `your-store`, `your-store.myshopify.com`, or a full admin URL.

Create a custom app in Shopify Admin with `read_orders`, `write_orders`, and `write_fulfillments`. Env values win over Settings when both are set.

Webhook: `POST /api/v1/shopify/webhook`  
Subscribe to `orders/create` and `orders/paid`. If `SHOPIFY_WEBHOOK_SECRET` (or the Settings secret) is set, FarmOS verifies `X-Shopify-Hmac-Sha256`.  
Manual pull: Orders page → Sync Shopify.

Line items match **SKU first**, then the product's **Shopify product ID**. Cancelled Shopify orders are ignored. Shipping a FarmOS order with a Shopify ID pushes tracking to Shopify fulfillments, and falls back to an order note if fulfillment is not available.

## Environment

`./install.sh` fills the required keys. To configure by hand instead:

```bash
cp .env.example .env
# set SECRET_KEY, POSTGRES_PASSWORD, PUBLIC_APP_URL
docker compose up -d --build
```

Important keys:

- `SECRET_KEY` — JWT and credential encryption
- `POSTGRES_PASSWORD`
- `SIMULATED_TIME_SCALE` — demo printers run faster than wall clock
- WooCommerce, Shopify, and SMTP / `NOTIFY_WEBHOOK_URL` as needed
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

Open Print FarmOS to clear the bed and start the next queued job.
```

The notification includes a button/link into that printer so the operator can confirm bed clear. Delivery history (time, event, printer, job, provider, sent/failed) lives under **Notifications**. Failed sends are logged there instead of being dropped.

## Filament inventory and FarmOS barcodes

Inventory starts **empty**. Manufacturer barcodes are **not** used. FarmOS generates its own codes, and filament information is entered **once** as a reusable **filament profile**:

- **Filament profile** (`FILT-SID-PETG-BLACK-3KG`) — manufacturer, product, material, colour, spool size, supplier, normal cost, temperatures, and reorder settings. Print this barcode for the shelf or receiving bench.
- **Physical spool** (`SPOOL-000142`) — one actual roll. Sequential numbers come from a locked database sequence and are never reused, including after a roll is emptied or archived.

Workflow: create the profile once → later open that profile (or scan its FILT- barcode) → **Add New Rolls** → quantity, optional price, location, and **drying** (needs drying, put in dryer now, already dry, or keep sealed) → **Create Rolls**. Choosing **Put in dryer now** places the new rolls on a dryer location and marks them as drying. FarmOS allocates the next SPOOL numbers and offers **Print All** / **Print Selected** (one per page, adhesive sheets, or a label printer). **Reprint Label** on an existing spool regenerates the same QR and number; it does not create a new roll. Spool detail can change drying later.

Each spool keeps the purchase price paid when it arrived, even if the profile’s normal price changes later.

Purchase orders can be received from the PO itself without scanning, including the same drying choice. Reorder modes: Off, Suggest only, **Create purchase order** (default), Approve and order, Full auto (architected, **disabled** unless spending controls explicitly enable it). Available stock = physical − committed (queue, current prints, production runs, waiting orders).

The shop-floor UI is phone-first: a bottom bar for Scan, Queue, Printers, QC, and Filament, plus a hamburger for the rest. Add FarmOS to the home screen as a PWA. Phone **SCAN** uses the camera (QR and Code 128) with manual entry as fallback. Scanning a profile barcode opens **Add New Rolls**.

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
- Role-ready (`admin`, `operator`, `packing`, `inventory`, `viewer`) — enforced on write APIs via `require_perm`, not only by hiding UI. Admin bypasses gates.
- Input validation via Pydantic
- Printer secrets encrypted; omitted from API responses
- Database migrations via Alembic (`create_all` also runs on boot for first install)
- Structured logging on the API and scheduler

## License

Private / internal print-farm tooling unless you add a license file.
