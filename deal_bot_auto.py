"""
Deal Bot — AUTOMATIC VERSION (100% FREE)
=========================================
Scrapes deals from Amazon, AliExpress, Jumia and Dealabs
using free RSS feeds and public pages. No API keys needed.

Setup:
  pip install python-telegram-bot requests schedule python-dotenv feedparser beautifulsoup4

.env file required:
  TELEGRAM_BOT_TOKEN=your_token_here
  TELEGRAM_CHANNEL_ID=@your_channel
  MIN_DISCOUNT_PCT=20
"""

import os
import re
import time
import logging
import schedule
import asyncio
import hashlib
import json
from datetime import datetime
from dotenv import load_dotenv
import requests
import feedparser
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID       = os.getenv("TELEGRAM_CHANNEL_ID")
MIN_DISCOUNT_PCT = int(os.getenv("MIN_DISCOUNT_PCT", 20))
POSTED_FILE      = "posted_deals.json"  # tracks already-posted deals

bot = Bot(token=TELEGRAM_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

# ── Already-posted tracker ─────────────────────────────────────────────────────
def load_posted() -> set:
    try:
        with open(POSTED_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_posted(posted: set):
    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted)[-500:], f)  # keep last 500

def deal_id(deal: dict) -> str:
    key = f"{deal.get('title', '')}{deal.get('url', '')}"
    return hashlib.md5(key.encode()).hexdigest()

# ── Store emojis ───────────────────────────────────────────────────────────────
STORE_EMOJI = {
    "amazon":     "📦",
    "ebay":       "🛒",
    "aliexpress": "🌏",
    "jumia":      "🛍️",
    "dealabs":    "🔥",
}

CATEGORY_EMOJI = {
    "tech":        "📱",
    "phones":      "📱",
    "audio":       "🎧",
    "computers":   "💻",
    "gaming":      "🎮",
    "fashion":     "👗",
    "shoes":       "👟",
    "home":        "🏠",
    "kitchen":     "🍳",
    "beauty":      "💄",
    "health":      "💊",
    "sports":      "⚽",
    "food":        "🍔",
    "kids":        "🧸",
    "travel":      "✈️",
    "general":     "📦",
}

# ── Smart category detector ────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "audio":     ["ecouteur", "earphone", "headphone", "casque", "bluetooth", "speaker", "enceinte", "airpod"],
    "phones":    ["phone", "iphone", "samsung", "smartphone", "mobile", "xiaomi", "redmi", "realme", "oppo"],
    "computers": ["laptop", "pc", "ordinateur", "computer", "tablet", "tablette", "ipad", "lenovo", "dell", "hp"],
    "gaming":    ["gaming", "playstation", "xbox", "nintendo", "manette", "controller", "game", "jeu"],
    "fashion":   ["shirt", "dress", "chemise", "robe", "veste", "jacket", "pull", "hoodie", "pantalon", "jean"],
    "shoes":     ["shoe", "sneaker", "basket", "chaussure", "boot", "sandale", "nike", "adidas"],
    "home":      ["sofa", "bed", "lit", "chaise", "table", "meuble", "furniture", "lampe", "lamp", "cushion"],
    "kitchen":   ["kitchen", "cuisine", "frigo", "refrigerator", "microwave", "blender", "cafetière", "coffee"],
    "beauty":    ["cream", "crème", "perfume", "parfum", "makeup", "lipstick", "shampoo", "skincare", "serum"],
    "health":    ["vitamin", "supplement", "mask", "masque", "sanitizer", "thermometer", "scale", "balance"],
    "sports":    ["sport", "gym", "fitness", "yoga", "vélo", "bike", "treadmill", "dumbbell", "haltère"],
    "kids":      ["kids", "enfant", "baby", "bébé", "toy", "jouet", "stroller", "poussette"],
    "food":      ["food", "nourriture", "snack", "chocolate", "café", "tea", "thé", "nuts"],
}

def detect_category(title: str) -> str:
    title_lower = title.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in title_lower:
                return category
    return "general"

# ── Telegram formatter ─────────────────────────────────────────────────────────
def format_telegram(deal: dict) -> str:
    store    = deal.get("store", "Unknown")
    s_emoji  = STORE_EMOJI.get(store.lower(), "🏪")
    title    = deal.get("title", "Amazing Deal")[:80]
    orig     = deal.get("original_price", "")
    sale     = deal.get("sale_price", "")
    pct      = deal.get("discount_pct", "")
    url      = deal.get("url", "")
    coupon   = deal.get("coupon", "")
    shipping = deal.get("free_shipping", False)

    # Auto-detect category from title
    category = detect_category(title)
    c_emoji  = CATEGORY_EMOJI.get(category, "📦")

    # Price line — always show original + sale if both exist
    if orig and sale:
        price_line = f"💰 <s>{orig}</s> → <b>{sale}</b> ({pct}% OFF)"
    elif sale and pct:
        price_line = f"💰 <b>{sale}</b> — {pct}% OFF"
    elif pct:
        price_line = f"💰 <b>{pct}% OFF</b>"
    else:
        price_line = f"💰 <b>{sale}</b>" if sale else ""

    coupon_line   = f"🎟 Coupon: <code>{coupon}</code>" if coupon else ""
    shipping_line = "🚚 FREE Shipping!" if shipping else ""
    link_line     = f'👉 <a href="{url}">Grab the deal</a>' if url else ""

    # Smart hashtags based on detected category
    tag_map = {
        "audio":     "#audio #ecouteurs #bluetooth",
        "phones":    "#smartphone #mobile #telephone",
        "computers": "#laptop #ordinateur #tech",
        "gaming":    "#gaming #jeux #console",
        "fashion":   "#mode #fashion #vetements",
        "shoes":     "#chaussures #shoes #sneakers",
        "home":      "#maison #home #deco",
        "kitchen":   "#cuisine #kitchen #electromenager",
        "beauty":    "#beaute #beauty #skincare",
        "health":    "#sante #health #bienetre",
        "sports":    "#sport #fitness #gym",
        "kids":      "#enfants #kids #jouets",
        "food":      "#food #nourriture #snacks",
        "general":   "#bonplan #promo",
    }
    category_tags = tag_map.get(category, "#bonplan")

    lines = [
        f"🔥 {c_emoji} <b>{title}</b>",
        "",
        price_line,
        f"🏪 Store: {store} {s_emoji}",
        coupon_line,
        shipping_line,
        "",
        link_line,
        "",
        "⏰ Limited time — act fast!",
        f"#deals #{store.lower().replace(' ', '')} {category_tags}",
    ]
    return "\n".join(l for l in lines if l is not None)


# ── Telegram poster ────────────────────────────────────────────────────────────
async def post_to_telegram(text: str) -> bool:
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )
        log.info("✅ Posted to Telegram!")
        return True
    except Exception as e:
        log.error(f"❌ Telegram error: {e}")
        return False


# ── SCRAPER 1: Dealabs RSS (best — covers all stores) ─────────────────────────
def scrape_dealabs() -> list:
    deals = []
    feeds = [
        "https://www.dealabs.com/rss/hot-deals",
        "https://www.dealabs.com/rss/nouveaux-deals",
    ]
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = entry.get("title", "")
                link  = entry.get("link", "")
                desc  = entry.get("summary", "")

                # Extract discount % from title or description
                pct_match = re.search(r'(\d+)\s*%', title + " " + desc)
                pct = pct_match.group(1) if pct_match else "0"

                # Extract price
                price_match = re.search(r'[\$€£]?\s*(\d+[.,]\d+)', desc)
                price = price_match.group(0) if price_match else ""

                # Detect store from title/link
                store = "Dealabs"
                for s in ["amazon", "aliexpress", "jumia", "ebay"]:
                    if s in title.lower() or s in link.lower() or s in desc.lower():
                        store = s.capitalize()
                        break

                deals.append({
                    "title":          title,
                    "store":          store,
                    "original_price": "",
                    "sale_price":     price,
                    "discount_pct":   pct,
                    "url":            link,
                    "coupon":         "",
                    "category":       "general",
                    "free_shipping":  "livraison gratuite" in desc.lower() or "free shipping" in desc.lower(),
                })
        except Exception as e:
            log.error(f"Dealabs RSS error: {e}")
    log.info(f"🔥 Dealabs: {len(deals)} deals found")
    return deals


# ── SCRAPER 2: Amazon deals page ───────────────────────────────────────────────
def scrape_amazon() -> list:
    deals = []
    urls = [
        "https://www.amazon.fr/deals",
        "https://www.amazon.eg/deals",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")

            for item in soup.select("[data-component-type='s-search-result']")[:10]:
                title_el = item.select_one("h2 span")
                price_el = item.select_one(".a-price .a-offscreen")
                orig_el  = item.select_one(".a-price.a-text-price .a-offscreen")
                link_el  = item.select_one("h2 a")
                badge_el = item.select_one(".a-badge-text")

                if not title_el or not price_el:
                    continue

                title = title_el.get_text(strip=True)
                sale  = price_el.get_text(strip=True)
                orig  = orig_el.get_text(strip=True) if orig_el else ""
                link  = "https://amazon.fr" + link_el["href"] if link_el else url
                badge = badge_el.get_text(strip=True) if badge_el else ""

                pct_match = re.search(r'(\d+)', badge)
                pct = pct_match.group(1) if pct_match else "0"

                deals.append({
                    "title":          title,
                    "store":          "Amazon",
                    "original_price": orig,
                    "sale_price":     sale,
                    "discount_pct":   pct,
                    "url":            link,
                    "coupon":         "",
                    "category":       "general",
                    "free_shipping":  False,
                })
        except Exception as e:
            log.error(f"Amazon scrape error: {e}")

    log.info(f"📦 Amazon: {len(deals)} deals found")
    return deals


# ── SCRAPER 3: AliExpress deals ────────────────────────────────────────────────
def scrape_aliexpress() -> list:
    deals = []
    try:
        url = "https://www.aliexpress.com/deals.htm"
        r   = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        for item in soup.select(".item-card")[:10]:
            title_el = item.select_one(".item-title")
            price_el = item.select_one(".sale-price")
            orig_el  = item.select_one(".orig-price")
            link_el  = item.select_one("a")
            disc_el  = item.select_one(".discount")

            if not title_el or not price_el:
                continue

            title = title_el.get_text(strip=True)
            sale  = price_el.get_text(strip=True)
            orig  = orig_el.get_text(strip=True) if orig_el else ""
            link  = "https:" + link_el["href"] if link_el and link_el.get("href", "").startswith("//") else (link_el["href"] if link_el else url)
            disc  = disc_el.get_text(strip=True) if disc_el else "0"

            pct_match = re.search(r'(\d+)', disc)
            pct = pct_match.group(1) if pct_match else "0"

            deals.append({
                "title":          title,
                "store":          "AliExpress",
                "original_price": orig,
                "sale_price":     sale,
                "discount_pct":   pct,
                "url":            link,
                "coupon":         "",
                "category":       "general",
                "free_shipping":  True,
            })
    except Exception as e:
        log.error(f"AliExpress scrape error: {e}")

    log.info(f"🌏 AliExpress: {len(deals)} deals found")
    return deals


# ── SCRAPER 4: Jumia deals ─────────────────────────────────────────────────────
def scrape_jumia() -> list:
    deals = []
    urls = [
        "https://www.jumia.ma/flash-sales/",
        "https://www.jumia.ma/deals-of-the-day/",
        "https://www.jumia.ma/mlp-toutes-les-promotions/",
    ]
    for url in urls:
        try:
            r    = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")

            for item in soup.select("article.prd")[:15]:
                title_el = item.select_one(".name")
                price_el = item.select_one(".prc")
                orig_el  = item.select_one(".old")
                disc_el  = item.select_one(".bdg._dsct")
                link_el  = item.select_one("a.core")

                if not title_el or not price_el:
                    continue

                title = title_el.get_text(strip=True)
                sale  = price_el.get_text(strip=True)
                orig  = orig_el.get_text(strip=True) if orig_el else ""
                disc  = disc_el.get_text(strip=True) if disc_el else "0"
                link  = "https://www.jumia.ma" + link_el["href"] if link_el else url

                pct_match = re.search(r'(\d+)', disc)
                pct = pct_match.group(1) if pct_match else "0"

                # Skip if no real discount info found
                if pct == "0" and not orig:
                    continue

                deals.append({
                    "title":          title,
                    "store":          "Jumia",
                    "original_price": orig,
                    "sale_price":     sale,
                    "discount_pct":   pct,
                    "url":            link,
                    "coupon":         "",
                    "category":       "general",
                    "free_shipping":  False,
                })
        except Exception as e:
            log.error(f"Jumia scrape error ({url}): {e}")

    log.info(f"🛍️ Jumia: {len(deals)} deals found")
    return deals


# ── Trigger check ──────────────────────────────────────────────────────────────
def meets_trigger(deal: dict) -> bool:
    try:
        pct = int(deal.get("discount_pct", 0))
    except Exception:
        pct = 0
    has_coupon = bool(deal.get("coupon"))
    is_flash   = deal.get("flash_sale", False)
    free_ship  = deal.get("free_shipping", False)
    if pct >= MIN_DISCOUNT_PCT: return True
    if has_coupon:               return True
    if is_flash:                 return True
    if free_ship and pct >= 10:  return True
    return False


# ── COUPON SCRAPER — free public sources ──────────────────────────────────────
def scrape_coupons() -> list:
    """
    Scrapes free promo codes from public coupon sites.
    Returns list of coupon deals to post separately.
    """
    coupons = []
    sources = [
        # Ma3ak (Morocco coupon site)
        {"url": "https://www.ma3ak.ma/feed/", "type": "rss"},
        # Dealabs promo codes RSS
        {"url": "https://www.dealabs.com/rss/codes-promo", "type": "rss"},
        # Coupert public feed
        {"url": "https://www.coupert.com/rss.xml", "type": "rss"},
    ]

    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:10]:
                title = entry.get("title", "")
                link  = entry.get("link", "")
                desc  = entry.get("summary", "")

                # Extract coupon code — look for patterns like CODE, PROMO20, SAVE10
                code_match = re.search(
                    r'\b([A-Z0-9]{4,15})\b',
                    title + " " + desc
                )
                code = code_match.group(1) if code_match else ""

                # Skip if no code found or code looks like a number only
                if not code or code.isdigit():
                    continue

                # Detect store
                store = "Unknown"
                for s in ["amazon", "aliexpress", "jumia", "ebay", "noon", "shein"]:
                    if s in title.lower() + desc.lower() + link.lower():
                        store = s.capitalize()
                        break

                # Extract discount %
                pct_match = re.search(r'(\d+)\s*%', title + " " + desc)
                pct = pct_match.group(1) if pct_match else ""

                coupons.append({
                    "title":          title[:80],
                    "store":          store,
                    "original_price": "",
                    "sale_price":     "",
                    "discount_pct":   pct,
                    "url":            link,
                    "coupon":         code,
                    "category":       "general",
                    "free_shipping":  False,
                    "is_coupon":      True,
                })
        except Exception as e:
            log.warning(f"Coupon source error: {e}")

    log.info(f"🎟 Coupons found: {len(coupons)}")
    return coupons


def format_coupon_telegram(deal: dict) -> str:
    """Special format for coupon-only posts."""
    store    = deal.get("store", "Unknown")
    s_emoji  = STORE_EMOJI.get(store.lower(), "🏪")
    title    = deal.get("title", "Promo Code")[:80]
    code     = deal.get("coupon", "")
    pct      = deal.get("discount_pct", "")
    url      = deal.get("url", "")

    pct_line  = f"💰 Save <b>{pct}%</b> with this code!" if pct else "💰 Use this code at checkout!"
    link_line = f'👉 <a href="{url}">Shop now</a>' if url else ""

    lines = [
        f"🎟 <b>PROMO CODE — {store} {s_emoji}</b>",
        "",
        f"📋 Code: <code>{code}</code>",
        "",
        pct_line,
        f"🛒 {title}",
        "",
        link_line,
        "",
        "⚡ Copy the code and use it at checkout!",
        f"#coupon #promocode #{store.lower()} #deals",
    ]
    return "\n".join(l for l in lines if l is not None)


# ── 24/7 keep-alive web server ─────────────────────────────────────────────────
def start_keepalive():
    """
    Starts a tiny web server so Railway/Render keeps the bot alive 24/7.
    Railway and Render ping the server every few minutes — without this
    they shut down free tier apps after inactivity.
    """
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Deal Bot is running!")
        def log_message(self, format, *args):
            pass  # suppress access logs

    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"🌐 Keep-alive server running on port {port}")


# ── Main auto scan ─────────────────────────────────────────────────────────────
def run_auto_scan():
    log.info("🤖 Auto-scan started...")
    posted = load_posted()

    # Scrape deals
    all_deals = (
        scrape_dealabs()
        + scrape_amazon()
        + scrape_aliexpress()
        + scrape_jumia()
    )

    # Scrape coupons separately
    all_coupons = scrape_coupons()

    new_posted = 0

    # Post deals
    for deal in all_deals:
        did = deal_id(deal)
        if did in posted:
            continue
        if meets_trigger(deal):
            try:
                text = format_telegram(deal)
                asyncio.run(post_to_telegram(text))
                posted.add(did)
                new_posted += 1
                time.sleep(5)
            except Exception as e:
                log.error(f"Error posting deal: {e}")

    # Post coupons
    for coupon in all_coupons:
        did = deal_id(coupon)
        if did in posted:
            continue
        if coupon.get("coupon"):  # only post if has a real code
            try:
                text = format_coupon_telegram(coupon)
                asyncio.run(post_to_telegram(text))
                posted.add(did)
                new_posted += 1
                time.sleep(5)
            except Exception as e:
                log.error(f"Error posting coupon: {e}")

    save_posted(posted)
    log.info(f"✅ Scan done — {new_posted} new posts ({len(all_deals)} deals + {len(all_coupons)} coupons scanned)")


# ── Manual deal post ───────────────────────────────────────────────────────────
def submit_manual_deal(
    title: str,
    store: str,
    original_price: str,
    sale_price: str,
    url: str,
    coupon: str = "",
    category: str = "general",
    free_shipping: bool = False,
):
    discount_pct = "?"
    try:
        orig = float(re.sub(r"[^\d.]", "", original_price))
        sale = float(re.sub(r"[^\d.]", "", sale_price))
        discount_pct = str(round((1 - sale / orig) * 100))
    except Exception:
        pass

    deal = {
        "title": title, "store": store,
        "original_price": original_price, "sale_price": sale_price,
        "discount_pct": discount_pct, "url": url,
        "coupon": coupon, "category": category,
        "free_shipping": free_shipping,
    }
    text = format_telegram(deal)
    print("\n=== TELEGRAM PREVIEW ===\n")
    print(text)
    asyncio.run(post_to_telegram(text))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Start keep-alive server for 24/7 hosting (Railway/Render)
    # Comment this out if running locally on your PC
    try:
        start_keepalive()
    except Exception:
        pass

    if len(sys.argv) > 1 and sys.argv[1] == "manual":
        submit_manual_deal(
            title="Your Product Name",
            store="Amazon",
            original_price="$100",
            sale_price="$60",
            url="https://amazon.com/your-link",
            category="tech",
            free_shipping=True,
        )
    else:
        log.info("🚀 Deal Bot started — scanning every hour")
        log.info(f"📊 Min discount: {MIN_DISCOUNT_PCT}% | Channel: {CHANNEL_ID}")
        run_auto_scan()  # run immediately on start
        schedule.every(1).hours.do(run_auto_scan)
        schedule.every(6).hours.do(lambda: log.info("💓 Bot still alive"))
        while True:
            schedule.run_pending()
            time.sleep(60)
