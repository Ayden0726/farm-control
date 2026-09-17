# Print FarmOS

Self-hosted production control for a 3D-printing farm. Print FarmOS is built around a **print queue**, not hobby printer monitoring: production jobs, G-code reuse, bed-clear confirmation, QC, finished-part inventory, filament costing, BOMs, and WooCommerce orders.

## Stack

- Next.js + React + TypeScript + Tailwind CSS (shop-floor UI)
- FastAPI + SQLAlchemy + Alembic
- PostgreSQL
- Redis (scheduler lock, slicer job queue)
- Docker Compose (`backend`, `worker`, `slicer-worker`, `frontend`)

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

The script installs Docker if needed (Linux), writes `.env` with random secrets (including slicer CPU/RAM limits), and starts the stack: API, UI, scheduler worker, **and slicer-worker** (PrusaSlicer). Open the URL it prints (usually `http://YOUR_SERVER_IP:3000`). First visit should land on `/setup`.

1. Complete the first-run setup wizard (admin account).
2. Uncheck **Load demo data** for a live shop. Leave it checked for a simulated farm (includes a sample handle STL for **Slicer**). To leave demo later, open **Settings → Demo mode** and choose **Turn off demo mode and restart**. That removes the sample Flex Rack 5 farm and simulated printers, sets print time to 1×, and restarts the app. Your admin account stays.
3. Add real printers (OctoPrint, Moonraker/Klipper, Creality K1/K2) when ready.

The first image build downloads PrusaSlicer and can take several minutes. After that, open **Slicer** at `/slicer`. You do not need a second command to start the slicer worker.

If login fails or the wizard does not appear, see **Wipe and reinstall** below.

If phones or other PCs will use a specific address:

```bash
./install.sh --host http://192.168.1.50:3000
```

## Wipe and reinstall

Use this when the wizard does not appear, login fails, you want a fresh database, or you are setting the farm up again on a machine that already ran FarmOS.

Run it **from the folder that contains `wipe-and-reinstall.sh` and `docker-compose.yml`**. Do not `cd farm-control` if you are already in that folder. A GitHub zip is often named `farm-control-main`.

```bash
ls wipe-and-reinstall.sh docker-compose.yml
chmod +x wipe-and-reinstall.sh
./wipe-and-reinstall.sh
```

If `./wipe-and-reinstall.sh` says **Permission denied**:

```bash
bash wipe-and-reinstall.sh
```

**Windows (Docker Desktop):**

```powershell
.\wipe-and-reinstall.ps1
```

That pulls the latest git (when this folder is a clone), **deletes the database** (orders, queue, inventory, users, settings), and reinstalls the app. The setup wizard at `/setup` runs again.

**Kept:** the `.env` file (secrets and `PUBLIC_APP_URL`).

Then open the URL the script prints (`Open:` LAN address and `Local: http://127.0.0.1:3000`) and complete setup. Uncheck **Load demo data** for a live shop.

To also throw away uploaded G-code and STLs, run `docker compose down -v` first, then `./wipe-and-reinstall.sh`.

## Everyday commands

Run these **from the folder that contains `install.sh`** (not from your home directory unless you `cd` there first):

```bash
./install.sh                 # first install (Linux / WSL)
./wipe-and-reinstall.sh      # wipe the database and reinstall
./update.sh                  # pull GitHub and rebuild (prints the URL when done)
docker compose down          # stop FarmOS
./scripts/backup.sh          # Postgres dump under ./backups/
```

Windows: `.\install.ps1`, `.\wipe-and-reinstall.ps1`, `.\update.ps1`.

## Production slicer (PrusaSlicer worker)

FarmOS does **not** implement a slicing engine. `./install.sh` / `.\install.ps1` start a dedicated `slicer-worker` with the rest of the stack. The web API only enqueues Redis jobs (`farmos:slicer:jobs`). Slicing cannot freeze the shop-floor UI.

To restart only the worker after changing CPU/RAM in `.env`:

```bash
docker compose up -d slicer-worker
```

The worker image (`backend/Dockerfile.slicer`) installs the official PrusaSlicer Linux AppImage. CPU and RAM limits are configurable:

```bash
SLICER_CPUS=2.0 SLICER_MEMORY=2g docker compose up -d slicer-worker
```

STL uploads are capped at **80 MB** (`STL_MAX_BYTES`). Files are type-checked, names are sanitised, and the worker uses an argv list (never a shell string). Packed STLs, G-code, and slicer profiles live on the `uploads` volume (`/data/stl`, `/data/gcode`, `/data/slicer_profiles`).

For local development without the AppImage, packing and plate preview still work. Slice jobs fail with a clear message unless `SLICER_BIN` points at `prusa-slicer` (or `backend/scripts/mock_prusa_slicer.py` in tests). Redis must be running for the worker to pick up jobs.

```bash
# slicer-worker (separate from the API)
cd backend && SLICER_BIN=prusa-slicer .venv/bin/python -m app.slicer_worker
```

## Public domain (`farm.yourdomain`)

In **Settings**, set **Public domain** to your site’s name (`example.com` or `myprintshop.au`). Print FarmOS then uses `https://farm.example.com` for printed QR codes, scan links, shipping-label QR codes, and other absolute FarmOS URLs. Typing `farm.example.com` or a full URL is not prefixed twice (`farm.farm.…` is not created). `www.example.com` is treated as the public website, so FarmOS still uses `farm.example.com`. Leave the field blank on a local PC — labels keep working with `farmos:` codes and relative `/scan/…` routes.

This field does not create DNS or TLS. Point an A or CNAME record for `farm.yourdomain` at this machine (or your reverse proxy). Localhost and LAN IPs are stored as typed, without a `farm.` prefix.

## Demo mode

If you checked **Load demo data** at setup, **Settings → Demo mode** can turn it off without wiping the database.

**Turn off demo mode and restart** removes the sample Flex Rack 5 catalog, simulated printers, demo jobs, and demo orders. It writes `SIMULATED_TIME_SCALE=1` into `.env` and recreates the API/worker containers so print time runs at wall clock. Your admin login, real printers, store credentials, and files you uploaded stay.

The site is unreachable for about a minute while containers restart. Refresh if the UI still looks like the demo farm.

To load demo data again, run `./wipe-and-reinstall.sh` and check **Load demo data** on the setup wizard.

## Update

In the app: **Settings → Update Print FarmOS**.

The first time (or after a reboot if the updater is not installed as a service), run this once on the server so the button can work:

```bash
./update.sh
```

Windows with Docker Desktop: `.\update.ps1`

That pulls the latest code and rebuilds containers (including the slicer-worker). Postgres data and uploaded G-code are kept. **Settings → Update Print FarmOS** is enabled once the stack is up — the API keeps a heartbeat and the `update-agent` container (or the in-process updater) runs `./update.sh` when you press the button.

When `./update.sh` finishes it prints the same addresses as install, for example:

```
Open:   http://YOUR_LAN_IP:3000
Local:  http://127.0.0.1:3000
Slicer: http://YOUR_LAN_IP:3000/slicer
```

`Open` uses `PUBLIC_APP_URL` from `.env` when set. Hard-refresh the browser (**Ctrl+Shift+R**) if the UI looks old.

The API is on port 8000 (`/docs` for OpenAPI). This is **not** a wipe — use `./wipe-and-reinstall.sh` if you need an empty farm.

## What the queue does

- Create a production run with multiple G-code files and copy counts. **Add from Products / BOM** explodes a catalog product onto the run: every required printed part, and every non-archived G-code tagged to that part. Hardware BOM lines are skipped. Optional accessories stay off unless you check the box. You can do the same on an existing run with **Add product from catalog**.
- Restrict which printers may take that run.
- The scheduler assigns queued jobs to compatible **idle** printers.
- When a print finishes, the printer is **Waiting for Bed Clear**. Nothing else starts on that machine until an operator confirms the bed is empty.
- **Settings → Automation** has **Assume the printer removes finished parts**, **off by default**. Print FarmOS does not command the print head to knock a part off. Turn this on only if the machine already clears the bed (belt printer, knock-off macro, etc.). Successful prints then go idle and the next job can start. Failed and cancelled prints still wait for bed clear.
- The queue runs **G-code**. Print FarmOS packs STLs on the printer’s **usable bed**, then the **slicer-worker** calls **PrusaSlicer CLI** and stores the result in the existing G-code library and print queue. Open **Slicer** (`/slicer`): choose a part → printer → Fill Plate → spacing/qty sliders → Slice → Approve & Queue. **Sliced Print Time** and filament m/g come from PrusaSlicer comments after a real slice; the live plate view shows a labelled **Pre-Slice Estimate** only. You can still upload G-code packed in Orca/PrusaSlicer on a workstation. A filename with a number plus `pcs` (`Handle-4pcs.gcode`) or `x` plus a number (`RK-FR5-Handle-x4.gcode`) sets **quantity**. Print time and filament grams also still come from slicer header/footer comments or filename tokens (`2h15m`, `48g`). Use **Library → Re-read estimates** to refresh files already on disk without re-uploading.
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
8. **Shipping** prints a FarmOS label from the store address, or an official Australia Post label when credentials are set. Recording carrier + tracking on Packing still updates WooCommerce/Shopify.

Hardware, packaging, and consumables are added as you buy them: **Hardware → New hardware SKU**, then **Add pcs** when a box arrives (pieces, not grams). Delete a SKU from the list or the profile. FarmOS does not preload a fastener catalog. Reorder modes match filament (off by default on new SKUs). Costing uses filament price, optional electricity ($/kWh × printer watts × hours), failure allowance, machine time, and hardware. Compatibility checks (nozzle, material, bed) block automatic assignment unless an administrator overrides.

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

Demo login after first-run setup with sample data: `ops@rackkit.local` / `rackkitfarm`.

## Shipping labels

The **Shipping** tab lists orders that can ship (packed / ready-to-ship, plus other open store orders). The to-address is the WooCommerce or Shopify shipping address captured when the order is synced.

Two label paths:

1. **Print FarmOS label** — always available. Print-ready A6 or A4 with from/to, order number, contents, and a barcode of the order public code. No Australia Post account required. This is the shop-floor fallback.
2. **Create Australia Post label** — when credentials are configured, FarmOS calls the official Shipping and Tracking REST API (create shipment → create labels → fetch PDF). Tracking and consignment IDs are stored on the order/shipment. Download or print the official PDF.

Missing AusPost credentials never block the UI. The official button explains that Settings still needs an API key, password, and account number.

### Australia Post credentials

Official API (not a third-party wrapper):

- Docs: Australia Post Shipping and Tracking REST API
- Test: `https://digitalapi.auspost.com.au/test/shipping/v1/`
- Live: `https://digitalapi.auspost.com.au/shipping/v1/`
- Auth: HTTP Basic (API key : password) plus `Account-Number` header

Save them in **Settings → Australia Post shipping**, or as optional env overrides:

```
AUSPOST_API_KEY=
AUSPOST_PASSWORD=
AUSPOST_ACCOUNT_NUMBER=
AUSPOST_SANDBOX=true
AUSPOST_BASE_URL=
```

`AUSPOST_SANDBOX=true` uses the test host. Set it false for live. Env values win over Settings when both are set. Secrets are encrypted at rest and masked on GET.

Ship-from name, street, suburb, state (NSW/VIC/QLD/SA/WA/TAS/NT/ACT), 4-digit postcode, phone, and email are required for official labels. Default service is Parcel Post (`AUS_PARCEL_REGULAR`) or Express Post (`AUS_PARCEL_EXPRESS`). Package weight defaults from printed-part grams when known, otherwise 500 g; operators can edit length/width/height per consignment.

Domestic AU only in this slice. Invalid postcode, missing suburb/state, or HTTP 401 are returned as clear errors — FarmOS does not invent tracking numbers that look like real AusPost consignments.

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
- `SIMULATED_TIME_SCALE` — demo printers run faster than wall clock. **Settings → Demo mode** sets this to `1` and restarts the stack.
- WooCommerce, Shopify, Australia Post, and SMTP / `NOTIFY_WEBHOOK_URL` as needed
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

The shop-floor UI is phone-first: a bottom bar for Scan, Queue, Printers, QC, and Filament, plus a hamburger for the rest. Add FarmOS to the home screen as a PWA. **SCAN** accepts a USB or Bluetooth barcode scanner plugged into the PC (HID keyboard wedge: it types the code and sends Enter), the phone camera (QR and Code 128), or manual entry. While you are logged in, scanning from anywhere in the app looks up FarmOS codes and opens the record. Dedicated scan fields on Scan / receive pages take the typed code so lookups are not fired twice. Scanning a profile barcode opens **Add New Rolls**.

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8472

# slicer-worker (optional; packing still works without PrusaSlicer)
python -m app.slicer_worker

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
