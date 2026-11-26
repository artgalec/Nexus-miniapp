import os
import re
import html
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from aiohttp import web, ClientSession
import feedparser

logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()

# 1. ПРОВЕРЕННЫЕ ОФИЦИАЛЬНЫЕ TELEGRAM-КАНАЛЫ И КОМЬЮНИТИ (без глобального Xiaomi)
TG_CHANNELS = [
    {"name": "Xiaomi Россия (Official)", "brand": "Xiaomi", "username": "xiaomirussia"},
    {"name": "Xiaomi Community Russia", "brand": "Xiaomi", "username": "miui_ru"},
    {"name": "Samsung Россия (Official)", "brand": "Samsung", "username": "Samsung_Russia"},
    {"name": "Huawei Mobile (Official)", "brand": "Huawei", "username": "huaweimobilerus"},
    {"name": "HONOR Россия (Official)", "brand": "HONOR", "username": "honor_russia"},
    {"name": "OPPO Россия (Official)", "brand": "OPPO", "username": "opporussia"},
    {"name": "vivo Россия (Official)", "brand": "vivo", "username": "vivorussia"},
    {"name": "realme Россия (Official)", "brand": "realme", "username": "realme_russia"},
    {"name": "Nothing (Official)", "brand": "Nothing", "username": "nothing"},
    {"name": "Telegram News", "brand": "Другое", "username": "telegram"},
]

# 2. ОФИЦИАЛЬНЫЕ САЙТЫ, NEWSROOM И КОМЬЮНИТИ БРЕНДОВ (RSS / Atom)
OFFICIAL_SITES_RSS = [
    {"name": "Xiaomi Community & Blog", "brand": "Xiaomi", "url": "https://blog.mi.com/en/feed/"},
    {"name": "Samsung Newsroom Global", "brand": "Samsung", "url": "https://news.samsung.com/global/feed"},
    {"name": "Samsung Newsroom Россия", "brand": "Samsung", "url": "https://news.samsung.com/ru/feed"},
    {"name": "Apple Newsroom", "brand": "Apple", "url": "https://www.apple.com/newsroom/rss-feed.rss"},
    {"name": "Google Official Blog", "brand": "Google", "url": "https://blog.google/rss/"},
    {"name": "Huawei Enterprise & News", "brand": "Huawei", "url": "https://www.huawei.com/en/rss-feeds/news"},
    {"name": "OnePlus Community", "brand": "OnePlus", "url": "https://community.oneplus.com/rss"},
    {"name": "Sony Electronics News", "brand": "Sony", "url": "https://www.sony.com/en/SonyInfo/News/Press/rss.xml"},
    {"name": "ASUS Pressroom", "brand": "ASUS", "url": "https://press.asus.com/feed/"},
    {"name": "Lenovo StoryHub", "brand": "Lenovo", "url": "https://news.lenovo.com/feed/"},
    {"name": "NVIDIA Official Blog", "brand": "NVIDIA", "url": "https://blogs.nvidia.com/feed/"},
    {"name": "AMD Newsroom", "brand": "AMD", "url": "https://ir.amd.com/news-events/press-releases/rss"},
]

# 3. ПРЯМОЙ ПАРСИНГ ОФИЦИАЛЬНЫХ ВЕБ-САЙТОВ БРЕНДОВ (у которых нет открытого RSS)
OFFICIAL_WEB_PAGES = [
    {
        "name": "Xiaomi Россия (mi.com/ru)",
        "brand": "Xiaomi",
        "url": "https://www.mi.com/ru/discover/",
        "link_pattern": r'href="(https?://www\.mi\.com/ru/discover/article\?id=\d+|/ru/discover/article\?id=\d+)"'
    },
    {
        "name": "Xiaomi Community (c.mi.com)",
        "brand": "Xiaomi",
        "url": "https://new.c.mi.com/ru/",
        "link_pattern": r'href="(https?://new\.c\.mi\.com/ru/post/\d+|/ru/post/\d+)"'
    },
    {
        "name": "HONOR Newsroom",
        "brand": "HONOR",
        "url": "https://www.honor.com/global/news/",
        "link_pattern": r'href="(https?://www\.honor\.com/global/news/[^"#?]+/|/global/news/[^"#?]+/)"'
    },
    {
        "name": "OPPO Newsroom",
        "brand": "OPPO",
        "url": "https://www.oppo.com/en/newsroom/",
        "link_pattern": r'href="(https?://www\.oppo\.com/en/newsroom/press/[^"#?]+/|/en/newsroom/press/[^"#?]+/)"'
    },
    {
        "name": "vivo Newsroom",
        "brand": "vivo",
        "url": "https://www.vivo.com/en/about-vivo/news",
        "link_pattern": r'href="(https?://www\.vivo\.com/en/about-vivo/news/[^"#?]+|/en/about-vivo/news/[^"#?]+)"'
    },
    {
        "name": "realme Newsroom",
        "brand": "realme",
        "url": "https://www.realme.com/global/newsroom",
        "link_pattern": r'href="(https?://www\.realme\.com/global/newsroom/[^"#?]+|/global/newsroom/[^"#?]+)"'
    },
    {
        "name": "Nothing Community",
        "brand": "Nothing",
        "url": "https://nothing.community/t/news",
        "link_pattern": r'href="(https?://nothing\.community/d/\d+-[^"#?]+|/d/\d+-[^"#?]+)"'
    },
]

# 4. ОФИЦИАЛЬНЫЕ СТРАНИЦЫ INSTAGRAM (username без @)
IG_PROFILES = [
    {"name": "Xiaomi Россия", "brand": "Xiaomi", "username": "xiaomi.russia"},
    {"name": "Samsung", "brand": "Samsung", "username": "samsung"},
    {"name": "Apple", "brand": "Apple", "username": "apple"},
    {"name": "Google", "brand": "Google", "username": "google"},
    {"name": "OPPO", "brand": "OPPO", "username": "oppo"},
    {"name": "OnePlus", "brand": "OnePlus", "username": "oneplus"},
    {"name": "Huawei Mobile", "brand": "Huawei", "username": "huaweimobile"},
    {"name": "HONOR Global", "brand": "HONOR", "username": "honorglobal"},
    {"name": "Nothing", "brand": "Nothing", "username": "nothing"},
    {"name": "vivo", "brand": "vivo", "username": "vivo_global"},
    {"name": "realme", "brand": "realme", "username": "realmeglobal"},
    {"name": "NVIDIA", "brand": "NVIDIA", "username": "nvidia"},
]

RSSHUB_MIRRORS = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub.moeyy.cn",
]

news_cache = []
last_updated = "Только что"
LOCAL_TZ = timezone(timedelta(hours=3))

def clean_html(raw_html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", raw_html or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def format_time_label(dt: datetime) -> str:
    local_dt = dt.astimezone(LOCAL_TZ)
    now = datetime.now(LOCAL_TZ)
    if local_dt.date() == now.date():
        return f"Сегодня, {local_dt.strftime('%H:%M')}"
    if local_dt.date() == (now - timedelta(days=1)).date():
        return f"Вчера, {local_dt.strftime('%H:%M')}"
    return local_dt.strftime("%d.%m в %H:%M")

def make_quick_summary(text: str, max_len: int = 210) -> str:
    cleaned = clean_html(text)
    if not cleaned:
        return "Официальная публикация на сайте бренда. Нажмите «Открыть источник»."
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len].rsplit(" ", 1)[0] + "..."

async def ai_summarize(title: str, text: str, session: ClientSession) -> str:
    if not GEMINI_API_KEY:
        return make_quick_summary(text)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        f"Переведи на русский (если текст на английском) и сделай короткую суть новости (1-2 предложения, до 180 символов, без вводных слов).\n"
        f"Заголовок: {title}\nТекст: {clean_html(text)[:1200]}"
    )
    try:
        async with session.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                ans = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if ans:
                    return ans
    except Exception:
        pass
    return make_quick_summary(text)

async def fetch_tg_channel(channel: dict, session: ClientSession) -> list:
    items = []
    url = f"https://t.me/s/{channel['username']}?t={int(datetime.now().timestamp())}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0.0.0 Mobile Safari/537.36",
        "Cache-Control": "no-cache"
    }
    try:
        async with session.get(url, headers=headers, timeout=12) as resp:
            if resp.status != 200:
                return items
            page = await resp.text()

        if "subscribers" not in page and "подписчик" not in page:
            return items

        msg_chunks = page.split('class="tgme_widget_message_wrap')
        for chunk in msg_chunks[1:]:
            post_match = re.search(r'data-post="([^"]+)"', chunk)
            time_match = re.search(r'<time[^>]+datetime="([^"]+)"', chunk)
            text_match = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>', chunk)

            if not post_match or not time_match:
                continue

            post_id = post_match.group(1)
            raw_time = time_match.group(1)
            try:
                dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.now(timezone.utc)

            cleaned = clean_html(text_match.group(1)) if text_match else ""
            if len(cleaned) < 15:
                continue

            title = cleaned[:85].rsplit(" ", 1)[0] + "..." if len(cleaned) > 85 else cleaned
            summary = await ai_summarize(title, cleaned, session)
            items.append({
                "title": title,
                "source": f"@{channel['username']}",
                "source_label": channel["name"],
                "brand": channel["brand"],
                "platform": "Telegram",
                "summary": summary,
                "url": f"https://t.me/{post_id}",
                "timestamp": dt.timestamp(),
                "time": format_time_label(dt),
                "is_fresh": (datetime.now(timezone.utc) - dt).total_seconds() <= 86400
            })
    except Exception as e:
        logging.warning("TG error %s: %s", channel["username"], e)

    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items[:6]

async def fetch_rss_site(source: dict, session: ClientSession) -> list:
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (NexusAI Official Site Reader)", "Cache-Control": "no-cache"}
    try:
        async with session.get(source["url"], headers=headers, timeout=12) as resp:
            if resp.status != 200:
                return items
            xml_text = await resp.text()
        feed = feedparser.parse(xml_text)
        for entry in feed.entries[:6]:
            title = clean_html(entry.get("title", ""))
            if not title:
                continue
            raw_desc = entry.get("summary", "") or entry.get("description", "")
            pub_str = entry.get("published") or entry.get("updated") or ""
            try:
                dt = parsedate_to_datetime(pub_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)

            summary = await ai_summarize(title, raw_desc, session)
            items.append({
                "title": title,
                "source": source["name"],
                "source_label": source["name"],
                "brand": source["brand"],
                "platform": "Оф. сайт",
                "summary": summary,
                "url": entry.get("link", "#"),
                "timestamp": dt.timestamp(),
                "time": format_time_label(dt),
                "is_fresh": (datetime.now(timezone.utc) - dt).total_seconds() <= 86400
            })
    except Exception as e:
        logging.warning("RSS site error %s: %s", source["name"], e)
    return items

async def fetch_official_web_page(site: dict, session: ClientSession) -> list:
    items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0.0.0 Mobile Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"
    }
    try:
        async with session.get(site["url"], headers=headers, timeout=12) as resp:
            if resp.status != 200:
                return items
            page = await resp.text()

        # Находим ссылки на новости/посты на официальной странице бренда
        raw_links = re.findall(site["link_pattern"], page)
        seen = set()
        clean_links = []
        for link in raw_links:
            full_url = urljoin(site["url"], link)
            if full_url not in seen and full_url != site["url"]:
                seen.add(full_url)
                clean_links.append(full_url)

        for idx, post_url in enumerate(clean_links[:5]):
            # Ищем заголовок рядом со ссылкой в HTML
            escaped = re.escape(post_url.replace("https://www.mi.com", "").replace("https://new.c.mi.com", ""))
            anchor_match = re.search(rf'<a[^>]+href="[^"]*{escaped}"[^>]*>([\s\S]*?)</a>', page)
            title = clean_html(anchor_match.group(1)) if anchor_match else ""
            if len(title) < 10:
                # Берём читаемый заголовок из конца URL, если тег <a> содержал только картинку
                slug = post_url.rstrip("/").split("/")[-1]
                slug = re.sub(r"^\d+-", "", slug).replace("-", " ").strip()
                title = slug.capitalize() if len(slug) > 8 else f"Новость на {site['name']}"

            # Ставим небольшое смещение по времени, чтобы сохранить порядок с главной страницы сайта
            dt = datetime.now(timezone.utc) - timedelta(minutes=idx * 25 + 15)
            items.append({
                "title": title[:95],
                "source": site["name"],
                "source_label": site["name"],
                "brand": site["brand"],
                "platform": "Оф. сайт",
                "summary": f"Официальная публикация на портале {site['name']}. Откройте страницу, чтобы прочитать полный текст.",
                "url": post_url,
                "timestamp": dt.timestamp(),
                "time": "На сайте",
                "is_fresh": True
            })
    except Exception as e:
        logging.warning("Web scrape error %s: %s", site["name"], e)
    return items

async def fetch_ig_profile(profile: dict, session: ClientSession) -> list:
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (NexusAI News Reader)", "Cache-Control": "no-cache"}
    xml_text = ""

    for mirror in RSSHUB_MIRRORS:
        rss_url = f"{mirror}/instagram/user/{profile['username']}"
        try:
            async with session.get(rss_url, headers=headers, timeout=8) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if "<rss" in text or "<feed" in text:
                        xml_text = text
                        break
        except Exception:
            continue

    if not xml_text:
        return items

    feed = feedparser.parse(xml_text)
    for entry in feed.entries[:4]:
        raw_desc = entry.get("summary", "") or entry.get("description", "") or entry.get("title", "")
        cleaned = clean_html(raw_desc)
        if not cleaned:
            cleaned = f"Официальная публикация @{profile['username']}"

        pub_str = entry.get("published") or entry.get("updated") or ""
        try:
            dt = parsedate_to_datetime(pub_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)

        title = cleaned[:85].rsplit(" ", 1)[0] + "..." if len(cleaned) > 85 else cleaned
        summary = await ai_summarize(title, cleaned, session)
        post_url = entry.get("link") or f"https://www.instagram.com/{profile['username']}/"
        items.append({
            "title": title,
            "source": f"@{profile['username']}",
            "source_label": profile["name"],
            "brand": profile["brand"],
            "platform": "Instagram",
            "summary": summary,
            "url": post_url,
            "timestamp": dt.timestamp(),
            "time": format_time_label(dt),
            "is_fresh": (datetime.now(timezone.utc) - dt).total_seconds() <= 86400
        })
    return items

async def refresh_all_news():
    global news_cache, last_updated
    async with ClientSession() as session:
        tasks = [fetch_tg_channel(ch, session) for ch in TG_CHANNELS]
        tasks += [fetch_rss_site(src, session) for src in OFFICIAL_SITES_RSS]
        tasks += [fetch_official_web_page(wp, session) for wp in OFFICIAL_WEB_PAGES]
        tasks += [fetch_ig_profile(ig, session) for ig in IG_PROFILES]
        results = await asyncio.gather(*tasks)

    seen_urls = set()
    combined = []
    for group in results:
        for item in group:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                combined.append(item)

    combined.sort(key=lambda x: x["timestamp"], reverse=True)

    for idx, item in enumerate(combined):
        item["id"] = f"{item['platform']}_{idx}"

    if combined:
        news_cache = combined
        last_updated = datetime.now(LOCAL_TZ).strftime("%H:%M")
        logging.info("Собрано официальных материалов: %d", len(news_cache))

async def handle_index(request):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <meta name="theme-color" content="#090d16">
        <title>NexusAI — Официальные сайты и соцсети брендов</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = { darkMode: 'class' };
        </script>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Inter, sans-serif;
                -webkit-tap-highlight-color: transparent;
            }
            .no-scrollbar::-webkit-scrollbar { display: none; }
            .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
        </style>
    </head>
    <body class="bg-slate-50 text-slate-900 dark:bg-[#090d16] dark:text-slate-100 pb-24 transition-colors duration-200">
        <header class="sticky top-0 z-30 backdrop-blur-md bg-white/90 dark:bg-[#090d16]/90 border-b border-slate-200 dark:border-slate-800/80">
            <div class="max-w-md mx-auto px-4 py-3 flex justify-between items-center">
                <div>
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <h1 class="text-lg font-extrabold tracking-tight bg-gradient-to-r from-sky-400 via-blue-500 to-emerald-400 bg-clip-text text-transparent">
                            NexusAI Official Feed
                        </h1>
                    </div>
                    <p id="status-text" class="text-[11px] text-slate-500 dark:text-slate-400">Поиск по оф. сайтам, TG и Instagram...</p>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="toggleTheme()" class="p-2 rounded-xl bg-slate-200/70 dark:bg-slate-800 text-xs font-bold">🌓</button>
                    <button id="refresh-btn" onclick="forceRefresh()" class="flex items-center gap-1 bg-blue-600 active:scale-95 transition text-white px-3 py-2 rounded-xl text-xs font-semibold shadow-md shadow-blue-600/20">
                        <span>↻</span> Обновить
                    </button>
                </div>
            </div>

            <div id="feed-controls" class="max-w-md mx-auto px-4 pb-3 space-y-2">
                <input id="search-input" oninput="applyFilters()" type="search" placeholder="Поиск: HyperOS, Xiaomi 17T, Galaxy, прошивка..."
                    class="w-full bg-slate-100 dark:bg-[#131a29] border border-slate-200 dark:border-slate-800 rounded-xl px-3.5 py-2 text-sm placeholder-slate-400 focus:outline-none focus:border-blue-500">
                
                <!-- Фильтр по времени и источникам -->
                <div class="flex gap-1.5 overflow-x-auto no-scrollbar">
                    <button id="fresh-btn" onclick="toggleFreshOnly()" class="px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">🔥 За 24ч</button>
                    <button onclick="setPlatform('Все')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap">Все</button>
                    <button onclick="setPlatform('Оф. сайт')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">🌐 Оф. сайты</button>
                    <button onclick="setPlatform('Telegram')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">✈️ Telegram</button>
                    <button onclick="setPlatform('Instagram')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">📸 Instagram</button>
                </div>

                <!-- Фильтр по брендам -->
                <div class="flex gap-1.5 overflow-x-auto no-scrollbar">
                    <button onclick="setBrand('Все')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-indigo-600 text-white whitespace-nowrap">Все бренды</button>
                    <button onclick="setBrand('Xiaomi')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Xiaomi</button>
                    <button onclick="setBrand('Samsung')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Samsung</button>
                    <button onclick="setBrand('Apple')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Apple</button>
                    <button onclick="setBrand('Google')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Google</button>
                    <button onclick="setBrand('Huawei')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Huawei</button>
                    <button onclick="setBrand('HONOR')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">HONOR</button>
                    <button onclick="setBrand('OPPO')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">OPPO</button>
                    <button onclick="setBrand('OnePlus')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">OnePlus</button>
                    <button onclick="setBrand('vivo')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">vivo</button>
                    <button onclick="setBrand('realme')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">realme</button>
                    <button onclick="setBrand('Nothing')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Nothing</button>
                    <button onclick="setBrand('Sony')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Sony</button>
                    <button onclick="setBrand('ASUS')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">ASUS</button>
                    <button onclick="setBrand('Lenovo')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Lenovo</button>
                    <button onclick="setBrand('NVIDIA')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">NVIDIA</button>
                    <button onclick="setBrand('AMD')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">AMD</button>
                </div>
            </div>
        </header>

        <main class="max-w-md mx-auto px-4 pt-4">
            <div id="news-list" class="space-y-3.5"></div>
        </main>

        <nav class="fixed bottom-0 inset-x-0 z-30 backdrop-blur-md bg-white/90 dark:bg-[#0d1320]/90 border-t border-slate-200 dark:border-slate-800">
            <div class="max-w-md mx-auto flex justify-around py-2">
                <button id="tab-feed" onclick="switchTab('feed')" class="flex flex-col items-center gap-0.5 text-blue-500 font-semibold text-xs px-6 py-1">
                    <span class="text-base">📰</span>
                    <span>Свежее</span>
                </button>
                <button id="tab-saved" onclick="switchTab('saved')" class="flex flex-col items-center gap-0.5 text-slate-400 font-medium text-xs px-6 py-1">
                    <span class="text-base">🔖</span>
                    <span>Избранное (<span id="saved-count">0</span>)</span>
                </button>
            </div>
        </nav>

        <script>
            let allNews = [];
            let currentPlatform = 'Все';
            let currentBrand = 'Все';
            let freshOnly = false;
            let currentTab = 'feed';
            let savedItems = JSON.parse(localStorage.getItem('nexus_social_saved') || '[]');

            function updateSavedCount() {
                document.getElementById('saved-count').innerText = savedItems.length;
            }

            function toggleTheme() {
                document.documentElement.classList.toggle('dark');
            }

            function toggleFreshOnly() {
                freshOnly = !freshOnly;
                const btn = document.getElementById('fresh-btn');
                btn.className = freshOnly
                    ? 'px-3 py-1 rounded-full text-xs font-semibold bg-emerald-600 text-white whitespace-nowrap'
                    : 'px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap';
                applyFilters();
            }

            function switchTab(tab) {
                currentTab = tab;
                const controls = document.getElementById('feed-controls');
                const tabFeed = document.getElementById('tab-feed');
                const tabSaved = document.getElementById('tab-saved');

                if (tab === 'feed') {
                    controls.style.display = 'block';
                    tabFeed.className = 'flex flex-col items-center gap-0.5 text-blue-500 font-semibold text-xs px-6 py-1';
                    tabSaved.className = 'flex flex-col items-center gap-0.5 text-slate-400 font-medium text-xs px-6 py-1';
                    applyFilters();
                } else {
                    controls.style.display = 'none';
                    tabSaved.className = 'flex flex-col items-center gap-0.5 text-blue-500 font-semibold text-xs px-6 py-1';
                    tabFeed.className = 'flex flex-col items-center gap-0.5 text-slate-400 font-medium text-xs px-6 py-1';
                    renderCards(savedItems);
                }
            }

            function toggleSave(url) {
                const idx = savedItems.findIndex(x => x.url === url);
                if (idx >= 0) {
                    savedItems.splice(idx, 1);
                } else {
                    const found = allNews.find(x => x.url === url);
                    if (found) savedItems.unshift(found);
                }
                localStorage.setItem('nexus_social_saved', JSON.stringify(savedItems));
                updateSavedCount();
                if (currentTab === 'saved') renderCards(savedItems);
                else applyFilters();
            }

            async function loadNews(force = false) {
                const list = document.getElementById('news-list');
                const btn = document.getElementById('refresh-btn');
                btn.disabled = true;
                btn.classList.add('opacity-60');
                if (!allNews.length) {
                    list.innerHTML = '<div class="text-center py-16 text-slate-400 text-sm">Собираем новости с официальных сайтов и каналов...</div>';
                }
                try {
                    const url = (force ? '/api/refresh' : '/api/news') + '?t=' + Date.now();
                    const res = await fetch(url);
                    const data = await res.json();
                    allNews = data.items || [];
                    document.getElementById('status-text').innerText = `Обновлено в ${data.updated} • ${allNews.length} материалов`;
                    if (currentTab === 'feed') applyFilters();
                } catch (e) {
                    list.innerHTML = '<div class="text-center py-12 text-red-400 text-sm">Ошибка загрузки. Нажмите «Обновить».</div>';
                } finally {
                    btn.disabled = false;
                    btn.classList.remove('opacity-60');
                }
            }

            function forceRefresh() {
                document.getElementById('status-text').innerText = 'Сканируем официальные сайты и соцсети...';
                loadNews(true);
            }

            function setPlatform(plat) {
                currentPlatform = plat;
                document.querySelectorAll('.plat-btn').forEach(b => {
                    const active = (plat === 'Все' && b.innerText === 'Все') || b.innerText.includes(plat);
                    b.className = active
                        ? 'plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap'
                        : 'plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap';
                });
                applyFilters();
            }

            function setBrand(brand) {
                currentBrand = brand;
                document.querySelectorAll('.brand-btn').forEach(b => {
                    const active = (brand === 'Все' && b.innerText.includes('Все')) || b.innerText === brand;
                    b.className = active
                        ? 'brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-indigo-600 text-white whitespace-nowrap'
                        : 'brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap';
                });
                applyFilters();
            }

            function applyFilters() {
                const query = document.getElementById('search-input').value.toLowerCase().trim();
                const filtered = allNews.filter(item => {
                    const matchFresh = !freshOnly || item.is_fresh;
                    const matchPlat = currentPlatform === 'Все' || item.platform === currentPlatform;
                    const matchBrand = currentBrand === 'Все' || item.brand === currentBrand;
                    const matchText = !query ||
                        item.title.toLowerCase().includes(query) ||
                        item.summary.toLowerCase().includes(query) ||
                        item.source.toLowerCase().includes(query) ||
                        item.source_label.toLowerCase().includes(query);
                    return matchFresh && matchPlat && matchBrand && matchText;
                });
                renderCards(filtered);
            }

            function renderCards(items) {
                const list = document.getElementById('news-list');
                if (!items.length) {
                    list.innerHTML = `<div class="text-center py-14 text-slate-400 text-sm">${
                        currentTab === 'saved' ? 'В избранном пока пусто' : 'Публикаций по выбранному фильтру пока нет'
                    }</div>`;
                    return;
                }
                list.innerHTML = '';
                items.forEach(item => {
                    const isSaved = savedItems.some(x => x.url === item.url);
                    const isIG = item.platform === 'Instagram';
                    const isSite = item.platform === 'Оф. сайт';
                    
                    let badgeClass = 'bg-sky-500/15 text-sky-400 border border-sky-500/25';
                    let borderClass = 'border-sky-500';
                    let labelColor = 'text-sky-400';
                    let icon = '✈️';

                    if (isIG) {
                        badgeClass = 'bg-pink-500/15 text-pink-500 border border-pink-500/25';
                        borderClass = 'border-pink-500';
                        labelColor = 'text-pink-400';
                        icon = '📸';
                    } else if (isSite) {
                        badgeClass = 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25';
                        borderClass = 'border-emerald-500';
                        labelColor = 'text-emerald-400';
                        icon = '🌐';
                    }

                    const card = document.createElement('article');
                    card.className = 'bg-white dark:bg-[#131a29] p-4 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm';
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-2 gap-2">
                            <span class="text-[11px] font-bold px-2.5 py-0.5 rounded-md truncate ${badgeClass}">
                                ${icon} ${item.source_label}
                            </span>
                            <span class="text-[11px] font-medium text-slate-500 dark:text-slate-400 shrink-0">${item.time}</span>
                        </div>
                        <h2 class="font-bold text-[15px] leading-snug mb-2.5">${item.title}</h2>
                        <div class="bg-slate-100 dark:bg-[#0b101b] p-3 rounded-xl mb-3 border-l-2 ${borderClass}">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-[11px] font-semibold ${labelColor}">⚡ ${item.platform}</span>
                                <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-500 dark:text-slate-400">${item.brand}</span>
                            </div>
                            <p class="text-xs leading-relaxed text-slate-600 dark:text-slate-300">${item.summary}</p>
                        </div>
                        <div class="flex gap-2">
                            <a href="${item.url}" target="_blank" rel="noopener" class="flex-1 text-center py-2 rounded-xl bg-slate-900 dark:bg-slate-800 hover:opacity-90 active:scale-[0.99] transition text-xs font-semibold text-white">
                                Открыть источник ↗
                            </a>
                            <button onclick="toggleSave('${item.url}')" class="px-3.5 py-2 rounded-xl border ${
                                isSaved
                                ? 'bg-amber-500/15 border-amber-500/40 text-amber-500'
                                : 'bg-slate-100 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-400'
                            } text-xs font-bold">
                                ${isSaved ? '★' : '☆'}
                            </button>
                        </div>
                    `;
                    list.appendChild(card);
                });
            }

            updateSavedCount();
            loadNews(false);
        </script>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type="text/html")

async def handle_api_news(request):
    if not news_cache:
        await refresh_all_news()
    return web.json_response({"items": news_cache, "updated": last_updated})

async def handle_api_refresh(request):
    await refresh_all_news()
    return web.json_response({"items": news_cache, "updated": last_updated})

async def periodic_updater():
    await refresh_all_news()
    while True:
        await asyncio.sleep(900)
        await refresh_all_news()

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get("/", handle_index),
        web.get("/api/news", handle_api_news),
        web.get("/api/refresh", handle_api_refresh),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Веб-сайт запущен на порту %s", port)

async def main():
    await asyncio.gather(
        start_web_server(),
        periodic_updater(),
    )

if __name__ == "__main__":
    asyncio.run(main())
