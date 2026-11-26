import os
import re
import html
import asyncio
import logging
from datetime import datetime
from aiohttp import web, ClientSession
import feedparser

logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()

# 1. ОФИЦИАЛЬНЫЕ TELEGRAM-КАНАЛЫ (username без @)
TG_CHANNELS = [
    {"name": "Xiaomi Official", "brand": "Xiaomi", "username": "xiaomi"},
    {"name": "Samsung Newsroom", "brand": "Samsung", "username": "samsungnewsroom"},
    {"name": "OPPO Global", "brand": "OPPO", "username": "oppoglobal"},
    {"name": "Huawei Mobile", "brand": "Huawei", "username": "HuaweiMobile"},
    {"name": "Nothing", "brand": "Nothing", "username": "nothing"},
    {"name": "vivo Global", "brand": "vivo", "username": "vivoglobal"},
    {"name": "Telegram News", "brand": "Другое", "username": "telegram"},
    {"name": "Rozetked", "brand": "Другое", "username": "rozetked"},
]

# 2. ОФИЦИАЛЬНЫЕ СТРАНИЦЫ INSTAGRAM (username без @)
IG_PROFILES = [
    {"name": "Xiaomi Global", "brand": "Xiaomi", "username": "xiaomi.global"},
    {"name": "Samsung", "brand": "Samsung", "username": "samsung"},
    {"name": "OPPO", "brand": "OPPO", "username": "oppo"},
    {"name": "Huawei Mobile", "brand": "Huawei", "username": "huaweimobile"},
    {"name": "Nothing", "brand": "Nothing", "username": "nothing"},
    {"name": "vivo", "brand": "vivo", "username": "vivo_global"},
]

# Зеркала RSSHub для публичных постов Instagram
RSSHUB_MIRRORS = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub.moeyy.cn",
]

news_cache = []
last_updated = "Только что"

def clean_html(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def make_quick_summary(text: str, max_len: int = 200) -> str:
    cleaned = clean_html(text)
    if not cleaned:
        return "Откройте пост в источнике, чтобы посмотреть фото и полный текст."
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len].rsplit(" ", 1)[0] + "..."

async def ai_summarize(title: str, text: str, session: ClientSession) -> str:
    if not GEMINI_API_KEY:
        return make_quick_summary(text)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        f"Сделай короткую выжимку новости на русском языке (1-2 предложения, до 180 символов, без вводных слов).\n"
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
    url = f"https://t.me/s/{channel['username']}"
    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"}
    try:
        async with session.get(url, headers=headers, timeout=12) as resp:
            if resp.status != 200:
                return items
            page = await resp.text()
        blocks = re.findall(
            r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>',
            page
        )
        for post_id, raw_msg in blocks[-3:]:
            cleaned = clean_html(raw_msg)
            if len(cleaned) < 25:
                continue
            title = cleaned[:75].rsplit(" ", 1)[0] + "..." if len(cleaned) > 75 else cleaned
            summary = await ai_summarize(title, cleaned, session)
            items.append({
                "title": title,
                "source": f"@{channel['username']}",
                "source_label": channel["name"],
                "brand": channel["brand"],
                "platform": "Telegram",
                "summary": summary,
                "url": f"https://t.me/{post_id}",
                "time": "Telegram"
            })
    except Exception as e:
        logging.warning("TG error %s: %s", channel["username"], e)
    return items

async def fetch_ig_profile(profile: dict, session: ClientSession) -> list:
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (NexusAI News Reader)"}
    xml_text = ""

    for mirror in RSSHUB_MIRRORS:
        rss_url = f"{mirror}/instagram/user/{profile['username']}"
        try:
            async with session.get(rss_url, headers=headers, timeout=10) as resp:
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
    for entry in feed.entries[:3]:
        raw_desc = entry.get("summary", "") or entry.get("description", "") or entry.get("title", "")
        cleaned = clean_html(raw_desc)
        if not cleaned:
            cleaned = f"Новая публикация в официальном аккаунте @{profile['username']}"
        title = cleaned[:75].rsplit(" ", 1)[0] + "..." if len(cleaned) > 75 else cleaned
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
            "time": "Instagram"
        })
    return items

async def refresh_all_news():
    global news_cache, last_updated
    async with ClientSession() as session:
        tasks = [fetch_tg_channel(ch, session) for ch in TG_CHANNELS]
        tasks += [fetch_ig_profile(ig, session) for ig in IG_PROFILES]
        results = await asyncio.gather(*tasks)

    combined = []
    max_len = max((len(r) for r in results), default=0)
    for i in range(max_len):
        for group in results:
            if i < len(group):
                item = group[i]
                item["id"] = f"{item['platform']}_{i}_{len(combined)}"
                combined.append(item)

    if combined:
        news_cache = combined
        last_updated = datetime.now().strftime("%H:%M")
        logging.info("Собрано постов: %d", len(news_cache))

async def handle_index(request):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <meta name="theme-color" content="#090d16">
        <title>NexusAI — Mobile Tech Feed</title>
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
                        <h1 class="text-lg font-extrabold tracking-tight bg-gradient-to-r from-sky-400 via-blue-500 to-pink-500 bg-clip-text text-transparent">
                            NexusAI Tech Feed
                        </h1>
                    </div>
                    <p id="status-text" class="text-[11px] text-slate-500 dark:text-slate-400">Загрузка официальных страниц...</p>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="toggleTheme()" class="p-2 rounded-xl bg-slate-200/70 dark:bg-slate-800 text-xs font-bold">🌓</button>
                    <button id="refresh-btn" onclick="forceRefresh()" class="flex items-center gap-1 bg-blue-600 active:scale-95 transition text-white px-3 py-2 rounded-xl text-xs font-semibold shadow-md shadow-blue-600/20">
                        <span>↻</span> Обновить
                    </button>
                </div>
            </div>

            <div id="feed-controls" class="max-w-md mx-auto px-4 pb-3 space-y-2">
                <input id="search-input" oninput="applyFilters()" type="search" placeholder="Поиск по брендам, моделям и тексту..."
                    class="w-full bg-slate-100 dark:bg-[#131a29] border border-slate-200 dark:border-slate-800 rounded-xl px-3.5 py-2 text-sm placeholder-slate-400 focus:outline-none focus:border-blue-500">
                
                <!-- Фильтр по соцсетям -->
                <div class="flex gap-1.5 overflow-x-auto no-scrollbar">
                    <button onclick="setPlatform('Все')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap">Все сети</button>
                    <button onclick="setPlatform('Telegram')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">✈️ Telegram</button>
                    <button onclick="setPlatform('Instagram')" class="plat-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">📸 Instagram</button>
                </div>

                <!-- Фильтр по брендам -->
                <div class="flex gap-1.5 overflow-x-auto no-scrollbar">
                    <button onclick="setBrand('Все')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-indigo-600 text-white whitespace-nowrap">Все бренды</button>
                    <button onclick="setBrand('Xiaomi')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Xiaomi</button>
                    <button onclick="setBrand('Samsung')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Samsung</button>
                    <button onclick="setBrand('OPPO')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">OPPO</button>
                    <button onclick="setBrand('Huawei')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Huawei</button>
                    <button onclick="setBrand('Nothing')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">Nothing</button>
                    <button onclick="setBrand('vivo')" class="brand-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">vivo</button>
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
                    <span>Лента</span>
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
            let currentTab = 'feed';
            let savedItems = JSON.parse(localStorage.getItem('nexus_social_saved') || '[]');

            function updateSavedCount() {
                document.getElementById('saved-count').innerText = savedItems.length;
            }

            function toggleTheme() {
                document.documentElement.classList.toggle('dark');
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
                    list.innerHTML = '<div class="text-center py-16 text-slate-400 text-sm">Собираем новости брендов из Telegram и Instagram...</div>';
                }
                try {
                    const res = await fetch(force ? '/api/refresh' : '/api/news');
                    const data = await res.json();
                    allNews = data.items || [];
                    document.getElementById('status-text').innerText = `Обновлено в ${data.updated} • ${allNews.length} постов`;
                    if (currentTab === 'feed') applyFilters();
                } catch (e) {
                    list.innerHTML = '<div class="text-center py-12 text-red-400 text-sm">Ошибка загрузки. Нажмите «Обновить».</div>';
                } finally {
                    btn.disabled = false;
                    btn.classList.remove('opacity-60');
                }
            }

            function forceRefresh() {
                document.getElementById('status-text').innerText = 'Обновление официальных страниц...';
                loadNews(true);
            }

            function setPlatform(plat) {
                currentPlatform = plat;
                document.querySelectorAll('.plat-btn').forEach(b => {
                    const active = (plat === 'Все' && b.innerText.includes('Все')) || b.innerText.includes(plat);
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
                    const matchPlat = currentPlatform === 'Все' || item.platform === currentPlatform;
                    const matchBrand = currentBrand === 'Все' || item.brand === currentBrand;
                    const matchText = !query ||
                        item.title.toLowerCase().includes(query) ||
                        item.summary.toLowerCase().includes(query) ||
                        item.source.toLowerCase().includes(query) ||
                        item.source_label.toLowerCase().includes(query);
                    return matchPlat && matchBrand && matchText;
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
                    const badgeClass = isIG
                        ? 'bg-pink-500/15 text-pink-500 border border-pink-500/25'
                        : 'bg-sky-500/15 text-sky-400 border border-sky-500/25';

                    const card = document.createElement('article');
                    card.className = 'bg-white dark:bg-[#131a29] p-4 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm';
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-2 gap-2">
                            <span class="text-[11px] font-bold px-2.5 py-0.5 rounded-md truncate ${badgeClass}">
                                ${isIG ? '📸' : '✈️'} ${item.source_label} (${item.source})
                            </span>
                            <span class="text-[11px] font-medium px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 shrink-0">${item.brand}</span>
                        </div>
                        <h2 class="font-bold text-[15px] leading-snug mb-2.5">${item.title}</h2>
                        <div class="bg-slate-100 dark:bg-[#0b101b] p-3 rounded-xl mb-3 border-l-2 ${isIG ? 'border-pink-500' : 'border-sky-500'}">
                            <div class="text-[11px] font-semibold ${isIG ? 'text-pink-400' : 'text-sky-400'} mb-1">⚡ Суть публикации</div>
                            <p class="text-xs leading-relaxed text-slate-600 dark:text-slate-300">${item.summary}</p>
                        </div>
                        <div class="flex gap-2">
                            <a href="${item.url}" target="_blank" rel="noopener" class="flex-1 text-center py-2 rounded-xl bg-slate-900 dark:bg-slate-800 hover:opacity-90 active:scale-[0.99] transition text-xs font-semibold text-white">
                                Открыть пост ↗
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
        await asyncio.sleep(1800)
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
