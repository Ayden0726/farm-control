from __future__ import annotations

from io import BytesIO
from pathlib import Path

import segno
from barcode import Code128
from barcode.writer import SVGWriter

from app.config import get_settings
from app.services.qr import qr_payload


def code128_svg(code: str) -> bytes:
    buf = BytesIO()
    Code128(code, writer=SVGWriter()).write(
        buf,
        {
            "module_width": 0.25,
            "module_height": 14,
            "quiet_zone": 2,
            "font_size": 8,
            "text_distance": 3,
            "write_text": True,
        },
    )
    return buf.getvalue()


def qr_png_bytes(kind: str, token: str, public_base: str = "") -> bytes:
    settings = get_settings()
    path = settings.qr_dir / f"{kind}-{token}.png"
    payload = qr_payload(kind, token, public_base)
    if not path.exists():
        qr = segno.make(payload, error="m")
        qr.save(str(path), scale=8, border=2)
    return Path(path).read_bytes()


def label_html_page(
    title: str,
    cards: list[dict],
    width_mm: float = 54,
    height_mm: float = 70,
    columns: int = 3,
) -> str:
    items = []
    for card in cards:
        barcode_img = (
            f'<img class="barcode" src="{card["barcode_url"]}" alt="{card["code"]}" />'
            if card.get("barcode_url")
            else ""
        )
        qr_img = f'<img class="qr" src="{card["qr_url"]}" alt="QR {card["code"]}" />'
        lines = "".join(f"<div class='line'>{line}</div>" for line in card.get("lines", []))
        items.append(
            f"""
            <article class="label">
              <div class="brand">RackKit FarmOS</div>
              <div class="title">{card.get("title", "")}</div>
              {lines}
              <div class="code">{card["code"]}</div>
              <div class="marks">{qr_img}{barcode_img}</div>
            </article>
            """
        )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    @page {{ margin: 8mm; size: auto; }}
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; background: #fff; color: #111; margin: 0; }}
    h1 {{ font-size: 14px; margin: 0 0 8px; }}
    .sheet {{
      display: grid;
      grid-template-columns: repeat({max(1, columns)}, {width_mm}mm);
      gap: 4mm;
      justify-content: start;
    }}
    .label {{
      width: {width_mm}mm;
      min-height: {height_mm}mm;
      border: 1px solid #222;
      padding: 3mm;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: 1.5mm;
      page-break-inside: avoid;
    }}
    .brand {{ font-size: 8px; letter-spacing: 0.18em; text-transform: uppercase; color: #555; }}
    .title {{ font-size: 13px; font-weight: 700; }}
    .line {{ font-size: 11px; }}
    .code {{ font-family: ui-monospace, monospace; font-size: 10px; word-break: break-all; }}
    .marks {{ display: flex; align-items: center; gap: 2mm; margin-top: auto; }}
    .qr {{ width: 22mm; height: 22mm; background: #fff; }}
    .barcode {{ height: 18mm; max-width: 100%; }}
    @media print {{
      .noprint {{ display: none; }}
      body {{ background: #fff; }}
    }}
  </style>
</head>
<body>
  <div class="noprint" style="padding:12px 16px;display:flex;justify-content:space-between;align-items:center">
    <h1>{title}</h1>
    <button onclick="window.print()">Print</button>
  </div>
  <div class="sheet">{"".join(items)}</div>
</body>
</html>
"""
