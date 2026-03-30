#!/usr/bin/env python3
"""
Hamilton Weekly Grocery Specials Scraper
Runs every Thursday, fetches live flyer data via Claude API (Haiku),
generates a static HTML site and an email-safe HTML version,
then sends to configured recipients via Resend.
"""

import os
import json
import re
import time
import datetime
import smtplib
from pathlib import Path
from typing import Optional
import httpx

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
RESEND_API_KEY    = os.environ["RESEND_API_KEY"]
FROM_EMAIL        = os.environ.get("FROM_EMAIL", "specials@yourdomain.com")
TO_EMAILS         = [e.strip() for e in os.environ.get("TO_EMAILS", "").split(",") if e.strip()]
SITE_URL          = os.environ.get("SITE_URL", "")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
RESEND_URL    = "https://api.resend.com/emails"
MODEL         = "claude-haiku-4-5-20251001"   # cheapest, plenty good for flyer extraction
MAX_TOKENS    = 4000
LB_TO_KG      = 2.20462

CATEGORIES = ["meat", "seafood", "veg", "fruit", "dairy", "other"]
CAT_NAMES  = {
    "meat":    "Meat & Poultry",
    "seafood": "Seafood & Fish",
    "veg":     "Vegetables",
    "fruit":   "Fruit",
    "dairy":   "Dairy & Eggs",
    "other":   "Grocery & Other",
}

# ── Sources ───────────────────────────────────────────────────────────────────
SOURCES = [
    {
        "id": "lococo",
        "name": "Lococo's",
        "color": "#993a20",
        "bg":    "#ffeee8",
        "instructions": (
            'Search for "Lococo\'s grocery Hamilton Ontario weekly specials flyer this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "fortinos",
        "name": "Fortinos",
        "color": "#a33800",
        "bg":    "#fdf0ec",
        "instructions": (
            'Search for "Fortinos flyer Hamilton Ontario this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "nofrills",
        "name": "No Frills",
        "color": "#7a6000",
        "bg":    "#fffbea",
        "instructions": (
            'Search for "No Frills flyer Ontario this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "freshco",
        "name": "FreshCo",
        "color": "#1a6b38",
        "bg":    "#eaf6ee",
        "instructions": (
            'Search for "FreshCo flyer Ontario this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "metro",
        "name": "Metro",
        "color": "#1a3ea8",
        "bg":    "#f0f4ff",
        "instructions": (
            'Search for "Metro supermarket flyer Ontario this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "sobeys",
        "name": "Sobeys",
        "color": "#a31f1f",
        "bg":    "#fff0f0",
        "instructions": (
            'Search for "Sobeys flyer Ontario this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "foodbasics",
        "name": "Food Basics",
        "color": "#6a1fa8",
        "bg":    "#f5eaff",
        "instructions": (
            'Search for "Food Basics flyer Ontario this week" and extract '
            "the current food/grocery specials (meat, produce, dairy, seafood, packaged food only)."
        ),
    },
    {
        "id": "walmart",
        "name": "Walmart",
        "color": "#8a6000",
        "bg":    "#fff8e1",
        "instructions": (
            'Search for "Walmart Canada Ontario flyer grocery this week" and extract '
            "food/grocery specials and Rollback deals (meat, produce, dairy, seafood, packaged food). "
            "Note Rollback items in the note field. Skip non-food."
        ),
    },
    {
        "id": "costco",
        "name": "Costco",
        "color": "#1a3cbf",
        "bg":    "#e8f0fe",
        "instructions": (
            'Search for "Costco Canada Ontario instant savings this week grocery" and extract '
            "food/grocery member savings (meat, seafood, produce, dairy, packaged food). "
            "Note bulk sizes in desc. Skip non-food."
        ),
    },
]

ITEM_SCHEMA = """\
Each item object must have:
- "name": product name (string)
- "desc": brand/variety/size info (string, "" if unknown)
- "cat": EXACTLY one of: "meat", "seafood", "veg", "fruit", "dairy", "other"
- "priceLb":   price per pound as number, or null
- "priceKg":   price per kg as number, or null (only if no lb price available)
- "priceFlat": flat/each/pack price as number, or null
- "unit":   unit description for flat price e.g. "each", "2 lb bag", "500g" — string or null
- "expiry": sale end date as "YYYY-MM-DD", or null
- "note":   short note like "Rollback", "Member Price", "Sale" — or null

Rules:
- Every item must have at least one non-null price field
- Prefer priceLb over priceKg when both are shown
- Return ONLY the raw JSON array — no markdown fences, no explanation"""


# ── API call ──────────────────────────────────────────────────────────────────
def fetch_source(source: dict, today: str) -> list[dict]:
    print(f"  Fetching {source['name']}…", flush=True)
    prompt = (
        f"Today is {today}. {source['instructions']}\n\n"
        f"Return a JSON array of the specials found. {ITEM_SCHEMA}"
    )
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "web-search-2025-03-05",
        "content-type": "application/json",
    }

    for attempt in range(4):
        resp = httpx.post(ANTHROPIC_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)
            print(f"    ⏳ Rate limited — waiting {wait}s (attempt {attempt + 1}/4)…", flush=True)
            time.sleep(wait)
            continue
        if not resp.is_success:
            print(f"    API error {resp.status_code}: {resp.text}", flush=True)
        resp.raise_for_status()
        break
    else:
        resp.raise_for_status()
    data = resp.json()

    text = "\n".join(
        b["text"] for b in data.get("content", []) if b.get("type") == "text"
    )

    # Extract JSON array from response
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        print(f"    ⚠  No JSON array found for {source['name']}. Response was:\n{text[:500]}")
        return []

    raw = match.group(0)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # Try fixing trailing commas
        cleaned = re.sub(r",(\s*[}\]])", r"\1", raw)
        try:
            items = json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    ⚠  JSON parse failed for {source['name']}")
            return []

    if not isinstance(items, list):
        return []

    normalized = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        price_lb    = item.get("priceLb")
        price_kg    = item.get("priceKg")
        price_flat  = item.get("priceFlat")
        if not any(isinstance(p, (int, float)) for p in [price_lb, price_kg, price_flat]):
            continue
        cat = item.get("cat", "other")
        if cat not in CATEGORIES:
            cat = "other"
        normalized.append({
            "name":      str(item.get("name", "")),
            "desc":      str(item.get("desc", "")),
            "cat":       cat,
            "priceLb":   float(price_lb)   if isinstance(price_lb,   (int, float)) else None,
            "priceKg":   float(price_kg)   if isinstance(price_kg,   (int, float)) else None,
            "priceFlat": float(price_flat) if isinstance(price_flat, (int, float)) else None,
            "unit":      str(item.get("unit", "")) if item.get("unit") else None,
            "expiry":    str(item.get("expiry", "")) if item.get("expiry") else None,
            "note":      str(item.get("note", ""))   if item.get("note")   else None,
            "store":     source["id"],
            "storeName": source["name"],
            "storeColor": source["color"],
            "storeBg":    source["bg"],
        })

    print(f"    ✓  {len(normalized)} items from {source['name']}")
    return normalized


def sort_price(item: dict) -> float:
    if item["priceLb"] is not None:
        return item["priceLb"]
    if item["priceKg"] is not None:
        return item["priceKg"] / LB_TO_KG
    return item["priceFlat"] or 9999.0


def format_price_html(item: dict) -> tuple[str, str]:
    """Returns (main_price_str, alt_price_str)"""
    if item["priceLb"] is not None:
        main = f"${item['priceLb']:.2f} <small>/lb</small>"
        alt  = f"${item['priceLb'] * LB_TO_KG:.2f}/kg"
    elif item["priceKg"] is not None:
        lb   = item["priceKg"] / LB_TO_KG
        main = f"${lb:.2f} <small>/lb</small>"
        alt  = f"${item['priceKg']:.2f}/kg"
    else:
        unit = item.get("unit") or ""
        main = f"${item['priceFlat']:.2f}"
        alt  = unit
    return main, alt


# ── HTML generation ───────────────────────────────────────────────────────────
def week_range(today: datetime.date) -> str:
    mon = today - datetime.timedelta(days=today.weekday())
    sun = mon + datetime.timedelta(days=6)
    mo  = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    if mon.month == sun.month:
        return f"{mo[mon.month-1]} {mon.day}–{sun.day}, {sun.year}"
    return f"{mo[mon.month-1]} {mon.day} – {mo[sun.month-1]} {sun.day}, {sun.year}"


def build_static_html(all_items: list[dict], week: str, generated_at: str) -> str:
    """Full interactive static HTML page."""
    items_json = json.dumps(all_items, ensure_ascii=False)
    total = len(all_items)
    store_counts = {}
    for item in all_items:
        store_counts[item["storeName"]] = store_counts.get(item["storeName"], 0) + 1

    store_badges = " ".join(
        f'<span style="display:inline-block;font-size:11px;font-family:monospace;'
        f'padding:2px 8px;border-radius:4px;background:{s["bg"]};color:{s["color"]};margin:2px">'
        f'{s["name"]} ({store_counts.get(s["name"],0)})</span>'
        for s in SOURCES
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hamilton Grocery Specials – {week}</title>
<style>
  :root{{--bg:#faf9f6;--surface:#fff;--surface2:#f3f1ed;--border:#e2dfd8;--text:#1a1917;--text2:#6b6860;--text3:#9b9890;--accent:#c84b2f;--amber:#9a5c00;--amber-light:#fdf4e3;--radius:10px}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:Georgia,serif;background:var(--bg);color:var(--text);min-height:100vh}}
  header{{background:var(--text);color:#fff;padding:1.25rem 2rem;display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap}}
  header h1{{font-size:1.4rem;font-weight:normal}}
  .week{{font-family:'Courier New',monospace;font-size:.73rem;color:#aaa;letter-spacing:.05em}}
  .toolbar{{background:var(--surface);border-bottom:1px solid var(--border);padding:.7rem 2rem;display:flex;gap:.6rem;flex-wrap:wrap;align-items:center}}
  .filter-btn{{font-family:inherit;font-size:.74rem;padding:.25rem .7rem;border:1px solid var(--border);border-radius:20px;background:var(--surface);cursor:pointer;color:var(--text2);transition:all .15s}}
  .filter-btn.active{{background:var(--text);color:#fff;border-color:var(--text)}}
  .filter-btn:hover:not(.active){{background:var(--surface2)}}
  .vr{{width:1px;height:22px;background:var(--border)}}
  .search-box{{font-family:inherit;font-size:.8rem;padding:.28rem .7rem;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);width:170px}}
  .search-box:focus{{outline:none;border-color:var(--text)}}
  main{{max-width:1200px;margin:0 auto;padding:1.25rem 2rem 3rem}}
  .meta{{font-size:.72rem;color:var(--text3);font-family:'Courier New',monospace;margin-bottom:1rem;line-height:1.7}}
  .image-only-box{{background:var(--amber-light);border:1px solid #e2c36a;border-radius:8px;padding:.7rem 1rem;margin-bottom:1.1rem;font-size:.77rem;color:var(--amber);line-height:1.5}}
  .image-only-box a{{color:var(--amber);font-weight:500}}
  .category-section{{margin-bottom:2rem}}
  .category-header{{display:flex;align-items:center;gap:.7rem;margin-bottom:.7rem;padding-bottom:.4rem;border-bottom:1.5px solid var(--border)}}
  .cat-pill{{font-size:.67rem;font-family:'Courier New',monospace;letter-spacing:.06em;padding:.17rem .6rem;border-radius:20px;text-transform:uppercase;font-weight:bold}}
  .cat-meat .cat-pill{{background:#fdf0ec;color:#c84b2f}}
  .cat-seafood .cat-pill{{background:#eaf1fb;color:#1a5fa8}}
  .cat-veg .cat-pill{{background:#edf6f0;color:#2d6a3f}}
  .cat-fruit .cat-pill{{background:#f9eef8;color:#b84fa8}}
  .cat-dairy .cat-pill{{background:#fdf4e3;color:#9a5c00}}
  .cat-other .cat-pill{{background:#f3f1ed;color:#5a5550}}
  .count{{font-size:.73rem;color:var(--text3)}}
  .items-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(265px,1fr));gap:.6rem}}
  .item-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:.8rem .95rem;display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;transition:border-color .15s}}
  .item-card:hover{{border-color:#bbb}}
  .item-left{{flex:1;min-width:0}}
  .item-name{{font-size:.87rem;line-height:1.35;margin-bottom:.18rem}}
  .item-desc{{font-size:.7rem;color:var(--text3);line-height:1.3;margin-bottom:.28rem;font-family:'Courier New',monospace}}
  .store-badge{{font-size:.64rem;font-family:'Courier New',monospace;padding:.12rem .42rem;border-radius:4px;display:inline-block}}
  .note-badge{{font-size:.62rem;color:var(--accent);font-family:'Courier New',monospace;margin-left:4px}}
  .expiry{{font-size:.63rem;color:var(--text3);font-family:'Courier New',monospace;margin-top:3px}}
  .expiry.soon{{color:var(--accent)}}
  .item-right{{text-align:right;flex-shrink:0}}
  .price-main{{font-size:1.08rem;font-family:'Courier New',monospace;font-weight:bold;line-height:1.1}}
  .price-main small{{font-size:.65rem;font-weight:normal;color:var(--text3)}}
  .price-alt{{font-size:.7rem;font-family:'Courier New',monospace;color:var(--text2);margin-top:1px}}
  .empty-state{{padding:2.5rem;text-align:center;color:var(--text3);font-style:italic;font-size:.88rem}}
  @media(max-width:600px){{header,.toolbar,main{{padding-left:1rem;padding-right:1rem}}.items-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <h1>🛒 Hamilton Grocery Specials</h1>
  <span class="week">{week}</span>
</header>
<div class="toolbar">
  <button class="filter-btn active" data-cat="all">All</button>
  <button class="filter-btn" data-cat="meat">🥩 Meat</button>
  <button class="filter-btn" data-cat="seafood">🐟 Seafood</button>
  <button class="filter-btn" data-cat="veg">🥦 Vegetables</button>
  <button class="filter-btn" data-cat="fruit">🍊 Fruit</button>
  <button class="filter-btn" data-cat="dairy">🧀 Dairy</button>
  <button class="filter-btn" data-cat="other">📦 Other</button>
  <span class="vr"></span>
  <input class="search-box" type="text" id="search" placeholder="Search items…" />
</div>
<main>
  <div class="meta">
    Generated {generated_at} &nbsp;·&nbsp; {total} specials found &nbsp;·&nbsp; {store_badges}
  </div>
  <div class="image-only-box">
    <strong>Image-only flyers (open directly):</strong>&nbsp;
    <a href="https://www.highlandpackers.com/weekly-specials-flyer.html" target="_blank">Highland Packers ↗</a>
    &nbsp;·&nbsp;
    <a href="https://www.nardinispecialties.ca/weekly-specials" target="_blank">Nardini Specialties ↗</a>
  </div>
  <div id="items-container"></div>
</main>
<script>
const ALL={{items:{items_json},cats:["meat","seafood","veg","fruit","dairy","other"],catNames:{{meat:"Meat & Poultry",seafood:"Seafood & Fish",veg:"Vegetables",fruit:"Fruit",dairy:"Dairy & Eggs",other:"Grocery & Other"}}}};
const LB_TO_KG=2.20462;
let cat="all",q="";
function sp(i){{if(i.priceLb!=null)return i.priceLb;if(i.priceKg!=null)return i.priceKg/LB_TO_KG;return i.priceFlat||9999;}}
function fmtExp(ds){{if(!ds)return null;const d=new Date(ds),now=new Date();now.setHours(0,0,0,0);if(isNaN(d))return null;const diff=Math.ceil((d-now)/86400000);const mo=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];if(diff<=0)return{{t:"Ends today",s:true}};if(diff===1)return{{t:"Ends tomorrow",s:true}};if(diff<=3)return{{t:diff+" days left",s:true}};return{{t:"Until "+mo[d.getMonth()]+" "+d.getDate(),s:false}};}}
function render(){{
  const filt=ALL.items.filter(i=>{{
    if(cat!=="all"&&i.cat!==cat)return false;
    if(q&&!`${{i.name}} ${{i.storeName}} ${{i.desc}}`.toLowerCase().includes(q))return false;
    return true;
  }});
  if(!filt.length){{document.getElementById("items-container").innerHTML="<div class=\\"empty-state\\">No matching specials.</div>";return;}}
  const cats=cat==="all"?ALL.cats:[cat];
  let html="";
  for(const c of cats){{
    const items=filt.filter(i=>i.cat===c).sort((a,b)=>sp(a)-sp(b));
    if(!items.length)continue;
    html+=`<div class="category-section cat-${{c}}"><div class="category-header"><span class="cat-pill">${{ALL.catNames[c]}}</span><span class="count">${{items.length}} deal${{items.length!==1?"s":""}}</span></div><div class="items-grid">`;
    for(const i of items){{
      let ph="",pa="";
      if(i.priceLb!=null){{ph=`$${{i.priceLb.toFixed(2)}} <small>/lb</small>`;pa=`$${{(i.priceLb*LB_TO_KG).toFixed(2)}}/kg`;}}
      else if(i.priceKg!=null){{const lb=i.priceKg/LB_TO_KG;ph=`$${{lb.toFixed(2)}} <small>/lb</small>`;pa=`$${{i.priceKg.toFixed(2)}}/kg`;}}
      else{{ph=`$${{i.priceFlat.toFixed(2)}}`;pa=i.unit||"";}}
      const exp=fmtExp(i.expiry);
      html+=`<div class="item-card"><div class="item-left"><div class="item-name">${{i.name}}</div>${{i.desc?`<div class="item-desc">${{i.desc}}</div>`:""}}<div><span class="store-badge" style="background:${{i.storeBg}};color:${{i.storeColor}}">${{i.storeName}}</span>${{i.note?`<span class="note-badge">${{i.note}}</span>`:""}}</div>${{exp?`<div class="expiry${{exp.s?" soon":""}}">${{exp.t}}</div>`:""}}</div><div class="item-right"><div class="price-main">${{ph}}</div><div class="price-alt">${{pa}}</div></div></div>`;
    }}
    html+="</div></div>";
  }}
  document.getElementById("items-container").innerHTML=html;
}}
document.querySelectorAll(".filter-btn").forEach(b=>b.addEventListener("click",()=>{{document.querySelectorAll(".filter-btn").forEach(x=>x.classList.remove("active"));b.classList.add("active");cat=b.dataset.cat;render();}}));
document.getElementById("search").addEventListener("input",e=>{{q=e.target.value.toLowerCase();render();}});
render();
</script>
</body>
</html>""".replace("{items_json}", items_json)


def build_email_html(all_items: list[dict], week: str, generated_at: str) -> str:
    """Email-safe HTML using tables and inline styles — works in Gmail, Outlook, Apple Mail."""
    cat_sections = ""

    for cat in CATEGORIES:
        items = [i for i in all_items if i["cat"] == cat]
        if not items:
            continue
        items.sort(key=sort_price)

        rows = ""
        for i, item in enumerate(items):
            main, alt = format_price_html(item, plain=True)
            bg = "#ffffff" if i % 2 == 0 else "#faf9f6"
            note_html = f' <span style="font-size:11px;color:#c84b2f">{item["note"]}</span>' if item.get("note") else ""
            expiry_html = ""
            if item.get("expiry"):
                expiry_html = f'<br><span style="font-size:11px;color:#9b9890;font-family:monospace">{item["expiry"]}</span>'

            rows += f"""
            <tr style="background:{bg}">
              <td style="padding:8px 12px;font-size:13px;border-bottom:1px solid #e2dfd8">
                <strong style="font-weight:500">{item["name"]}</strong>
                {f'<br><span style="font-size:11px;color:#9b9890;font-family:monospace">{item["desc"]}</span>' if item["desc"] else ""}
              </td>
              <td style="padding:8px 12px;font-size:11px;border-bottom:1px solid #e2dfd8;white-space:nowrap">
                <span style="display:inline-block;background:{item['storeBg']};color:{item['storeColor']};padding:2px 6px;border-radius:3px;font-family:monospace;font-size:10px">{item["storeName"]}</span>{note_html}{expiry_html}
              </td>
              <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #e2dfd8;white-space:nowrap;font-family:monospace">
                <strong style="font-size:14px">{main}</strong>
                <br><span style="font-size:11px;color:#6b6860">{alt}</span>
              </td>
            </tr>"""

        # Category header color
        pill_colors = {
            "meat":    ("#c84b2f", "#fdf0ec"),
            "seafood": ("#1a5fa8", "#eaf1fb"),
            "veg":     ("#2d6a3f", "#edf6f0"),
            "fruit":   ("#b84fa8", "#f9eef8"),
            "dairy":   ("#9a5c00", "#fdf4e3"),
            "other":   ("#5a5550", "#f3f1ed"),
        }
        txt_c, bg_c = pill_colors[cat]

        cat_sections += f"""
        <tr><td colspan="3" style="padding:0">
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:24px">
            <tr>
              <td style="padding:12px 12px 8px;border-bottom:2px solid #e2dfd8">
                <span style="display:inline-block;background:{bg_c};color:{txt_c};font-size:10px;font-family:monospace;letter-spacing:1px;text-transform:uppercase;font-weight:bold;padding:3px 10px;border-radius:20px">{CAT_NAMES[cat]}</span>
                <span style="font-size:11px;color:#9b9890;margin-left:8px">{len(items)} deals</span>
              </td>
            </tr>
            {rows}
          </table>
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hamilton Grocery Specials – {week}</title>
</head>
<body style="margin:0;padding:0;background:#f3f1ed;font-family:Georgia,serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f1ed;padding:24px 0">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden">

      <!-- Header -->
      <tr>
        <td style="background:#1a1917;padding:20px 24px">
          <h1 style="color:#fff;font-size:20px;font-weight:normal;margin:0">🛒 Hamilton Grocery Specials</h1>
          <p style="color:#aaa;font-size:11px;font-family:monospace;margin:4px 0 0;letter-spacing:1px">{week}</p>
        </td>
      </tr>

      <!-- Image-only notice -->
      <tr>
        <td style="padding:12px 24px;background:#fdf4e3;border-bottom:1px solid #e2c36a">
          <p style="margin:0;font-size:12px;color:#9a5c00;line-height:1.5">
            <strong>Image-only flyers (open directly):</strong>
            <a href="https://www.highlandpackers.com/weekly-specials-flyer.html" style="color:#9a5c00">Highland Packers</a>
            &nbsp;·&nbsp;
            <a href="https://www.nardinispecialties.ca/weekly-specials" style="color:#9a5c00">Nardini Specialties</a>
          </p>
        </td>
      </tr>

      <!-- Items -->
      <tr><td style="padding:0 24px 24px">
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:16px">
          {cat_sections}
        </table>
      </td></tr>

      <!-- Footer -->
      <tr>
        <td style="padding:16px 24px;background:#f3f1ed;border-top:1px solid #e2dfd8">
          <p style="margin:0;font-size:11px;color:#9b9890;font-family:monospace;line-height:1.6">
            Generated {generated_at} · {len(all_items)} specials<br>
            Prices from publicly available flyers. Always verify at store.
            {f'<br><a href="{SITE_URL}" style="color:#9b9890">{SITE_URL}</a>' if SITE_URL else ""}
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def format_price_html(item: dict, plain: bool = False) -> tuple[str, str]:
    if item["priceLb"] is not None:
        main = f"${item['priceLb']:.2f}/lb"
        alt  = f"${item['priceLb'] * LB_TO_KG:.2f}/kg"
    elif item["priceKg"] is not None:
        lb   = item["priceKg"] / LB_TO_KG
        main = f"${lb:.2f}/lb"
        alt  = f"${item['priceKg']:.2f}/kg"
    else:
        unit = item.get("unit") or ""
        main = f"${item['priceFlat']:.2f}"
        alt  = unit
    return main, alt


# ── Email sending ─────────────────────────────────────────────────────────────
def send_email(subject: str, html_body: str, to_emails: list[str]) -> None:
    if not to_emails:
        print("  ⚠  No recipients configured — skipping email send.")
        return
    if not RESEND_API_KEY:
        print("  ⚠  No RESEND_API_KEY — skipping email send.")
        return

    for to in to_emails:
        payload = {
            "from": FROM_EMAIL,
            "to":   [to],
            "subject": subject,
            "html": html_body,
        }
        resp = httpx.post(
            RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            print(f"  ✓  Email sent to {to}")
        else:
            print(f"  ✗  Email to {to} failed: {resp.status_code} {resp.text}")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    today      = datetime.date.today()
    today_str  = today.isoformat()
    week       = week_range(today)
    gen_at     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    print(f"\n🛒 Hamilton Grocery Specials — {week}")
    print(f"   Fetching {len(SOURCES)} sources with {MODEL}…\n")

    all_items = []
    for i, source in enumerate(SOURCES):
        if i > 0:
            time.sleep(45)
        try:
            items = fetch_source(source, today_str)
            all_items.extend(items)
        except Exception as e:
            print(f"  ✗  {source['name']} failed: {e}")

    print(f"\n✓ Total items collected: {len(all_items)}")

    # Write data JSON (used by GitHub Pages / static site)
    out_dir = Path("dist")
    out_dir.mkdir(exist_ok=True)

    with open(out_dir / "data.json", "w", encoding="utf-8") as f:
        json.dump({"week": week, "generatedAt": gen_at, "items": all_items}, f, ensure_ascii=False, indent=2)
    print("✓ Wrote dist/data.json")

    # Write static HTML
    static_html = build_static_html(all_items, week, gen_at)
    with open(out_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(static_html)
    print("✓ Wrote dist/index.html")

    # Write email HTML
    email_html = build_email_html(all_items, week, gen_at)
    with open(out_dir / "email.html", "w", encoding="utf-8") as f:
        f.write(email_html)
    print("✓ Wrote dist/email.html")

    # Send email
    subject = f"🛒 Hamilton Grocery Specials – {week}"
    print(f"\n📧 Sending to {len(TO_EMAILS)} recipient(s)…")
    send_email(subject, email_html, TO_EMAILS)

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
