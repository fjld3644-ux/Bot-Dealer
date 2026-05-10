"""
Deal Bot — AUTOMATIC VERSION (100% FREE, NO DUPLICATES)
========================================================
Uses a local JSON file + in-memory cache to prevent duplicates.
Scans Dealabs, Jumia, AliExpress every 3 hours.

Setup:
  pip install python-telegram-bot requests schedule python-dotenv beautifulsoup4

.env file:
  TELEGRAM_BOT_TOKEN=your_token
  TELEGRAM_CHANNEL_ID=@your_channel
  MIN_DISCOUNT_PCT=20
"""

import os, re, time, logging, schedule, asyncio, hashlib, json
from datetime import datetime
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from telegram import Bot
from telegram.constants import ParseMode

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID       = os.getenv("TELEGRAM_CHANNEL_ID")
MIN_DISCOUNT_PCT = int(os.getenv("MIN_DISCOUNT_PCT", 20))

bot = Bot(token=TELEGRAM_TOKEN)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Duplicate prevention ───────────────────────────────────────────────────────
# POSTED_IDS lives in memory for the whole Railway session.
# It is also saved to posted.json so it survives short restarts.
POSTED_IDS: set = set()

async def init_memory():
    global POSTED_IDS
    try:
        with open("posted.json") as f:
            POSTED_IDS = set(json.load(f).get("ids", []))
        log.info(f"📋 Loaded {len(POSTED_IDS)} posted IDs")
    except Exception:
        POSTED_IDS = set()
        log.info("📋 Fresh start")

def is_posted(did: str) -> bool:
    return did in POSTED_IDS

def mark_posted(did: str):
    POSTED_IDS.add(did)
    try:
        with open("posted.json", "w") as f:
            json.dump({"ids": list(POSTED_IDS)[-1000:], "ts": datetime.now().isoformat()}, f)
    except Exception:
        pass  # memory still works

def deal_id(deal: dict) -> str:
    if deal.get("is_coupon") and deal.get("coupon"):
        return hashlib.md5(f"coupon_{deal['coupon']}".encode()).hexdigest()
    key = f"{deal.get('title','')[:50]}{deal.get('url','')[:80]}"
    return hashlib.md5(key.encode()).hexdigest()

# ── Store + category ───────────────────────────────────────────────────────────
STORE_EMOJI = {"amazon":"📦","ebay":"🛒","aliexpress":"🌏","jumia":"🛍️","dealabs":"🔥","shein":"👗","noon":"🌙"}

CATEGORY_KEYWORDS = {
    "audio":     ["ecouteur","earphone","headphone","casque","bluetooth","speaker","enceinte","airpod","tws"],
    "phones":    ["phone","iphone","samsung","smartphone","mobile","xiaomi","redmi","realme","oppo","tecno","infinix"],
    "computers": ["laptop","pc","ordinateur","computer","tablet","tablette","ipad","lenovo","dell","asus"],
    "gaming":    ["gaming","playstation","xbox","nintendo","manette","controller","ps4","ps5"],
    "fashion":   ["shirt","dress","chemise","robe","veste","jacket","pull","hoodie","pantalon","jean"],
    "shoes":     ["shoe","sneaker","basket","chaussure","boot","sandale","nike","adidas","puma"],
    "home":      ["sofa","bed","lit","chaise","table","meuble","furniture","lampe","matelas"],
    "kitchen":   ["kitchen","cuisine","frigo","refrigerator","microwave","blender","cafetiere","coffee"],
    "beauty":    ["cream","creme","perfume","parfum","makeup","lipstick","shampoo","skincare","serum"],
    "health":    ["vitamin","supplement","mask","masque","thermometer","balance"],
    "sports":    ["sport","gym","fitness","yoga","velo","bike","treadmill","dumbbell","running"],
    "kids":      ["kids","enfant","baby","bebe","toy","jouet","stroller","poussette"],
}
CATEGORY_EMOJI = {"audio":"🎧","phones":"📱","computers":"💻","gaming":"🎮","fashion":"👗","shoes":"👟","home":"🏠","kitchen":"🍳","beauty":"💄","health":"💊","sports":"⚽","kids":"🧸","general":"📦"}
TAG_MAP = {"audio":"#audio #ecouteurs","phones":"#smartphone #mobile","computers":"#laptop #tech","gaming":"#gaming #jeux","fashion":"#mode #vetements","shoes":"#chaussures #sneakers","home":"#maison #deco","kitchen":"#cuisine","beauty":"#beaute #skincare","health":"#sante","sports":"#sport #fitness","kids":"#enfants","general":"#bonplan"}

def detect_category(title: str) -> str:
    t = title.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return cat
    return "general"

# ── Formatters ─────────────────────────────────────────────────────────────────
def format_deal(deal: dict) -> str:
    store    = deal.get("store","Unknown")
    s_emoji  = STORE_EMOJI.get(store.lower(),"🏪")
    title    = deal.get("title","Deal")[:80]
    orig     = deal.get("original_price","")
    sale     = deal.get("sale_price","")
    pct      = deal.get("discount_pct","")
    url      = deal.get("url","")
    coupon   = deal.get("coupon","")
    shipping = deal.get("free_shipping", False)
    cat      = detect_category(title)
    c_emoji  = CATEGORY_EMOJI.get(cat,"📦")
    tags     = TAG_MAP.get(cat,"#bonplan")

    if orig and sale:   price = f"💰 <s>{orig}</s> → <b>{sale}</b> ({pct}% OFF)"
    elif sale and pct:  price = f"💰 <b>{sale}</b> — {pct}% OFF"
    elif pct:           price = f"💰 <b>{pct}% OFF</b>"
    else:               price = f"💰 <b>{sale}</b>" if sale else ""

    lines = [
        f"🔥 {c_emoji} <b>{title}</b>","",price,
        f"🏪 {store} {s_emoji}",
        f"🎟 Coupon: <code>{coupon}</code>" if coupon else "",
        "🚚 FREE Shipping!" if shipping else "","",
        f'👉 <a href="{url}">Grab the deal</a>' if url else "","",
        "⏰ Limited time — act fast!",
        f"#deals #{store.lower().replace(' ','')} {tags}",
    ]
    return "\n".join(l for l in lines if l)

def format_coupon(deal: dict) -> str:
    store   = deal.get("store","Dealabs")
    s_emoji = STORE_EMOJI.get(store.lower(),"🏪")
    title   = deal.get("title","")[:80]
    code    = deal.get("coupon","")
    pct     = deal.get("discount_pct","")
    amt     = deal.get("discount_amt","")
    url     = deal.get("url","").split(" ")[0].strip()
    saving  = f"💰 Save <b>{pct}%</b>!" if pct else (f"💰 Save <b>{amt}€</b>!" if amt else "💰 Savings at checkout!")
    lines = [
        f"🎟️ <b>PROMO CODE — {store} {s_emoji}</b>","",
        f"🔑 Code: <code>{code}</code>","👆 Tap the code to copy it!","",
        saving,f"📌 {title}" if title else "","",
        f'🛒 <a href="{url}">Shop now</a>' if url else "",
        "⚡ Limited time — use before it expires!",
        f"#coupon #promocode #{store.lower().replace(' ','')} #deals",
    ]
    return "\n".join(l for l in lines if l)

# ── Telegram ───────────────────────────────────────────────────────────────────
async def post_to_telegram(text: str) -> bool:
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        log.info("✅ Posted!")
        return True
    except Exception as e:
        log.error(f"❌ {e}")
        return False

# ── RSS parser ─────────────────────────────────────────────────────────────────
def parse_rss(url: str) -> list:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        root = ET.fromstring(r.content)
        return [{"title": i.findtext("title",""), "link": i.findtext("link",""), "desc": BeautifulSoup(i.findtext("description",""), "html.parser").get_text()} for i in root.findall(".//item")]
    except Exception as e:
        log.warning(f"RSS error: {e}")
        return []

# ── Scrapers ───────────────────────────────────────────────────────────────────
def scrape_dealabs() -> list:
    deals = []
    for url in ["https://www.dealabs.com/rss/hot-deals","https://www.dealabs.com/rss/nouveaux-deals"]:
        for e in parse_rss(url)[:15]:
            pct = re.search(r'(\d+)\s*%', e["title"]+" "+e["desc"])
            price = re.search(r'[\$€£]\s*\d+[.,]\d+', e["desc"])
            store = next((s.capitalize() for s in ["amazon","aliexpress","jumia","ebay"] if s in (e["title"]+e["desc"]+e["link"]).lower()), "Dealabs")
            deals.append({"title":e["title"],"store":store,"original_price":"","sale_price":price.group(0) if price else "","discount_pct":pct.group(1) if pct else "0","url":e["link"],"coupon":"","free_shipping":"livraison gratuite" in e["desc"].lower()})
    log.info(f"🔥 Dealabs: {len(deals)}")
    return deals

def scrape_jumia() -> list:
    deals = []
    for url in ["https://www.jumia.ma/flash-sales/","https://www.jumia.ma/deals-of-the-day/"]:
        try:
            soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=10).text, "html.parser")
            for item in soup.select("article.prd")[:15]:
                t=item.select_one(".name"); p=item.select_one(".prc"); o=item.select_one(".old"); d=item.select_one(".bdg._dsct"); a=item.select_one("a.core")
                if not t or not p: continue
                pct=re.search(r'(\d+)', d.get_text() if d else "0")
                orig=o.get_text(strip=True) if o else ""
                if not pct and not orig: continue
                deals.append({"title":t.get_text(strip=True),"store":"Jumia","original_price":orig,"sale_price":p.get_text(strip=True),"discount_pct":pct.group(1) if pct else "0","url":"https://www.jumia.ma"+a["href"] if a else url,"coupon":"","free_shipping":False})
        except Exception as e: log.error(f"Jumia: {e}")
    log.info(f"🛍️ Jumia: {len(deals)}")
    return deals

def scrape_aliexpress() -> list:
    deals = []
    try:
        soup = BeautifulSoup(requests.get("https://www.aliexpress.com/deals.htm", headers=HEADERS, timeout=10).text, "html.parser")
        for item in soup.select(".item-card")[:10]:
            t=item.select_one(".item-title"); p=item.select_one(".sale-price"); o=item.select_one(".orig-price"); d=item.select_one(".discount"); a=item.select_one("a")
            if not t or not p: continue
            pct=re.search(r'(\d+)', d.get_text() if d else "0")
            deals.append({"title":t.get_text(strip=True),"store":"AliExpress","original_price":o.get_text(strip=True) if o else "","sale_price":p.get_text(strip=True),"discount_pct":pct.group(1) if pct else "0","url":("https:" if a and a.get("href","").startswith("//") else "")+(a["href"] if a else ""),"coupon":"","free_shipping":True})
    except Exception as e: log.error(f"AliExpress: {e}")
    log.info(f"🌏 AliExpress: {len(deals)}")
    return deals

def scrape_coupons() -> list:
    coupons = []
    SKIP = {"HTTP","HTTPS","HTML","FREE","SALE","DEAL","CODE","PROMO","AVEC","POUR","DANS","PLUS","SANS","OFFRE","VOIR"}
    for url in ["https://www.dealabs.com/rss/codes-promo","https://www.ma3ak.ma/feed/"]:
        for e in parse_rss(url)[:10]:
            full = e["title"]+" "+e["desc"]
            m = re.search(r'\b([A-Z][A-Z0-9]{3,14})\b', full)
            if not m: continue
            code = m.group(1)
            if code in SKIP or code.isdigit(): continue
            store_map = {"amazon":"Amazon","aliexpress":"AliExpress","jumia":"Jumia","ebay":"eBay","shein":"Shein","noon":"Noon","cdiscount":"Cdiscount"}
            store = next((name for key,name in store_map.items() if key in (full+e["link"]).lower()), "Dealabs")
            pct_m = re.search(r'(\d+)\s*%', full)
            amt_m = re.search(r'(\d+)[€$]\s*(?:de réduction|off|discount)', full)
            clean = re.sub(r'\[.*?\]', '', e["title"].replace(code,"")).strip(" -–|")[:80]
            coupons.append({"title":clean,"store":store,"coupon":code,"discount_pct":pct_m.group(1) if pct_m else "","discount_amt":amt_m.group(1) if amt_m else "","url":e["link"].split(" ")[0],"is_coupon":True})
    log.info(f"🎟 Coupons: {len(coupons)}")
    return coupons

# ── Trigger ────────────────────────────────────────────────────────────────────
def meets_trigger(deal: dict) -> bool:
    try: pct = int(deal.get("discount_pct", 0))
    except: pct = 0
    return pct >= MIN_DISCOUNT_PCT or bool(deal.get("coupon")) or deal.get("flash_sale") or (deal.get("free_shipping") and pct >= 10)

# ── Keep-alive ─────────────────────────────────────────────────────────────────
def start_keepalive():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
        def log_message(self, *a): pass
    port = int(os.getenv("PORT", 8080))
    threading.Thread(target=HTTPServer(("0.0.0.0", port), H).serve_forever, daemon=True).start()
    log.info(f"🌐 Keep-alive on :{port}")

# ── Main scan ──────────────────────────────────────────────────────────────────
def run_auto_scan():
    log.info("🤖 Scanning all sources...")
    items = scrape_dealabs() + scrape_jumia() + scrape_aliexpress() + scrape_coupons()
    posted = 0
    for item in items:
        did = deal_id(item)
        if is_posted(did):
            continue
        if not meets_trigger(item):
            continue
        try:
            text = format_coupon(item) if item.get("is_coupon") else format_deal(item)
            if asyncio.run(post_to_telegram(text)):
                mark_posted(did)
                posted += 1
                time.sleep(8)
        except Exception as e:
            log.error(f"Error: {e}")
    log.info(f"✅ {posted} new posts | {len(POSTED_IDS)} total tracked")

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    asyncio.run(init_memory())
    try: start_keepalive()
    except: pass
    log.info(f"🚀 Bot started | Min discount: {MIN_DISCOUNT_PCT}% | Channel: {CHANNEL_ID}")
    run_auto_scan()
    schedule.every(3).hours.do(run_auto_scan)
    while True:
        schedule.run_pending()
        time.sleep(60)
