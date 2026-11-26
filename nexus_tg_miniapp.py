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

RSS_SOURCES = [
    {"name": "Habr", "category": "Разработка", "url": "https://habr.com/ru/rss/articles/?fl=ru"},
    {"name": "Reddit AI", "category": "ИИ", "url": "https://www.reddit.com/r/artificial/.rss"},
    {"name": "GitHub Blog", "category": "GitHub", "url": "https://github.blog/feed/"},
    {"name": "3DNews", "category": "Железо", "url": "https://3dnews.ru/news/rss/"},
]

TG_CHANNELS = [
    {"name": "Rozetked", "category": "Гаджеты", "username": "rozetked"},
    {"name": "Код Дурова", "category": "Технологии", "username": "kodru"},
]

news_cache = []
last_updated = "Только что"

def clean_html(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def make_quick_summary(text: str, max_len: int = 190) -> str:
    cleaned = clean_html(text)
    if not cleaned:
        return "Откройте источник, чтобы прочитать полную статью."
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

async def fetch_rss_feed(source: dict, session: ClientSession) -> list:
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (NexusAI Mobile Web)"}
    try:
        async with session.get(source["url"], headers=headers, timeout=12) as resp:
            if resp.status != 200:
                return items
            xml_text = await resp.text()
        feed = feedparser.parse(xml_text)
        for entry in feed.entries[:5]:
            title = clean_html(entry.get("title", "Без заголовка"))
            raw_desc = entry.get("summary", "") or entry.get("description", "")
            summary = await ai_summarize(title, raw_desc, session)
            items.append({
                "title": title,
                "source": source["name"],
                "category": source["category"],
                "summary": summary,
                "url": entry.get("link", "#"),
                "time": entry.get("published", "Сегодня")[:16]
            })
    except Exception as e:
        logging.warning("RSS error %s: %s", source["name"], e)
    return items

async def fetch_tg_channel(channel: dict, session: ClientSession) -> list:
    items = []
    url = f"https://t.me/s/{channel['username']}"
    try:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12) as resp:
            if resp.status != 200:
                return items
            page = await resp.text()
        blocks = re.findall(
            r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>',
            page
        )
        for post_id, raw_msg in blocks[-4:]:
            cleaned = clean_html(raw_msg)
            if len(cleaned) < 30:
                continue
            title = cleaned[:78].rsplit(" ", 1)[0] + "..." if len(cleaned) > 78 else cleaned
            summary = await ai_summarize(title, cleaned, session)
            items.append({
                "title": title,
                "source": channel["name"],
                "category": channel["category"],
                "summary": summary,
                "url": f"https://t.me/{post_id}",
                "time": "Сегодня"
            })
    except Exception as e:
        logging.warning("TG error %s: %s", channel["username"], e)
    return items

async def refresh_all_news():
    global news_cache, last_updated
    async with ClientSession() as session:
        tasks = [fetch_rss_feed(src, session) for src in RSS_SOURCES]
        tasks += [fetch_tg_channel(ch, session) for ch in TG_CHANNELS]
        results = await asyncio.gather(*tasks)

    combined = []
    max_len = max((len(r) for r in results), default=0)
    for i in range(max_len):
        for group in results:
            if i < len(group):
                item = group[i]
                item["id"] = f"{item['source']}_{i}_{len(combined)}"
                combined.append(item)

    if combined:
        news_cache = combined
        last_updated = datetime.now().strftime("%H:%M")

async def handle_index(request):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <meta name="theme-color" content="#090d16">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <title>NexusAI — Мобильный техно-дайджест</title>
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
        <!-- Верхняя закреплённая панель -->
        <header class="sticky top-0 z-30 backdrop-blur-md bg-white/85 dark:bg-[#090d16]/85 border-b border-slate-200 dark:border-slate-800/80">
            <div class="max-w-md mx-auto px-4 py-3 flex justify-between items-center">
                <div>
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <h1 class="text-lg font-extrabold tracking-tight bg-gradient-to-r from-blue-500 to-indigo-400 bg-clip-text text-transparent">
                            NexusAI News
                        </h1>
                    </div>
                    <p id="status-text" class="text-[11px] text-slate-500 dark:text-slate-400">Загрузка дайджеста...</p>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="toggleTheme()" aria-label="Тема" class="p-2 rounded-xl bg-slate-200/70 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-bold">
                        🌓
                    </button>
                    <button id="refresh-btn" onclick="forceRefresh()" class="flex items-center gap-1 bg-blue-600 active:scale-95 transition text-white px-3 py-2 rounded-xl text-xs font-semibold shadow-md shadow-blue-600/20">
                        <span>↻</span> Обновить
                    </button>
                </div>
            </div>

            <!-- Поиск и категории (только на вкладке Лента) -->
            <div id="feed-controls" class="max-w-md mx-auto px-4 pb-3">
                <input id="search-input" oninput="applyFilters()" type="search" placeholder="Поиск: ИИ, GitHub, процессор..."
                    class="w-full bg-slate-100 dark:bg-[#131a29] border border-slate-200 dark:border-slate-800 rounded-xl px-3.5 py-2 text-sm placeholder-slate-400 focus:outline-none focus:border-blue-500 mb-2.5">
                <div class="flex gap-1.5 overflow-x-auto no-scrollbar">
                    <button onclick="setCategory('Все')" class="cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap">Все</button>
                    <button onclick="setCategory('ИИ')" class="cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">🤖 ИИ</button>
                    <button onclick="setCategory('GitHub')" class="cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">💻 GitHub</button>
                    <button onclick="setCategory('Разработка')" class="cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">⚙️ Код</button>
                    <button onclick="setCategory('Железо')" class="cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">🔌 Железо</button>
                    <button onclick="setCategory('Гаджеты')" class="cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap">📱 Гаджеты</button>
                </div>
            </div>
        </header>

        <!-- Контент -->
        <main class="max-w-md mx-auto px-4 pt-4">
            <div id="news-list" class="space-y-3.5"></div>
        </main>

        <!-- Нижняя мобильная навигация -->
        <nav class="fixed bottom-0 inset-x-0 z-30 backdrop-blur-md bg-white/90 dark:bg-[#0d1320]/90 border-t border-slate-200 dark:border-slate-800">
            <div class="max-w-md mx-auto flex justify-around py-2">
                <button id="tab-feed" onclick="switchTab('feed')" class="flex flex-col items-center gap-0.5 text-blue-500 font-semibold text-xs px-6 py-1">
                    <span class="text-base">📰</span>
                    <span>Лента</span>
                </button>
                <button id="tab-saved" onclick="switchTab('saved')" class="flex flex-col items-center gap-0.5 text-slate-400 font-medium text-xs px-6 py-1">
                    <span class="text-base">🔖</span>
                    <span>Сохранённое (<span id="saved-count">0</span>)</span>
                </button>
            </div>
        </nav>

        <script>
            let allNews = [];
            let currentCategory = 'Все';
            let currentTab = 'feed';
            let savedItems = JSON.parse(localStorage.getItem('nexus_saved') || '[]');

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
                localStorage.setItem('nexus_saved', JSON.stringify(savedItems));
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
                    list.innerHTML = '<div class="text-center py-16 text-slate-400 text-sm">Собираем свежие новости...</div>';
                }
                try {
                    const res = await fetch(force ? '/api/refresh' : '/api/news');
                    const data = await res.json();
                    allNews = data.items || [];
                    document.getElementById('status-text').innerText = `Обновлено в ${data.updated} • ${allNews.length} статей`;
                    if (currentTab === 'feed') applyFilters();
                } catch (e) {
                    list.innerHTML = '<div class="text-center py-12 text-red-400 text-sm">Ошибка загрузки. Нажмите «Обновить».</div>';
                } finally {
                    btn.disabled = false;
                    btn.classList.remove('opacity-60');
                }
            }

            function forceRefresh() {
                document.getElementById('status-text').innerText = 'Сбор свежих публикаций...';
                loadNews(true);
            }

            function setCategory(cat) {
                currentCategory = cat;
                document.querySelectorAll('.cat-btn').forEach(b => {
                    if (b.innerText.includes(cat)) {
                        b.className = 'cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap';
                    } else {
                        b.className = 'cat-btn px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-[#131a29] text-slate-600 dark:text-slate-300 whitespace-nowrap';
                    }
                });
                applyFilters();
            }

            function applyFilters() {
                const query = document.getElementById('search-input').value.toLowerCase().trim();
                const filtered = allNews.filter(item => {
                    const matchCat = currentCategory === 'Все' || item.category === currentCategory;
                    const matchText = !query ||
                        item.title.toLowerCase().includes(query) ||
                        item.summary.toLowerCase().includes(query) ||
                        item.source.toLowerCase().includes(query);
                    return matchCat && matchText;
                });
                renderCards(filtered);
            }

            function renderCards(items) {
                const list = document.getElementById('news-list');
                if (!items.length) {
                    list.innerHTML = `<div class="text-center py-14 text-slate-400 text-sm">${
                        currentTab === 'saved' ? 'В закладках пока пусто' : 'Ничего не найдено'
                    }</div>`;
                    return;
                }
                list.innerHTML = '';
                items.forEach(item => {
                    const isSaved = savedItems.some(x => x.url === item.url);
                    const card = document.createElement('article');
                    card.className = 'bg-white dark:bg-[#131a29] p-4 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm';
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-400">${item.source}</span>
                            <span class="text-[11px] text-slate-400">${item.category} • ${item.time}</span>
                        </div>
                        <h2 class="font-bold text-[15px] leading-snug mb-2.5">${item.title}</h2>
                        <div class="bg-slate-100 dark:bg-[#0b101b] p-3 rounded-xl mb-3 border-l-2 border-indigo-500">
                            <div class="text-[11px] font-semibold text-indigo-500 dark:text-indigo-400 mb-1">⚡ Краткая суть</div>
                            <p class="text-xs leading-relaxed text-slate-600 dark:text-slate-300">${item.summary}</p>
                        </div>
                        <div class="flex gap-2">
                            <a href="${item.url}" target="_blank" rel="noopener" class="flex-1 text-center py-2 rounded-xl bg-slate-900 dark:bg-slate-800 hover:opacity-90 active:scale-[0.99] transition text-xs font-semibold text-white">
                                Читать полностью ↗
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
    logging.info("Мобильный веб-сайт запущен на порту %s", port)

async def main():
    await asyncio.gather(
        start_web_server(),
        periodic_updater(),
    )

if __name__ == "__main__":
    asyncio.run(main())
