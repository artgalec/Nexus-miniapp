import os
import re
import html
import asyncio
import logging
from datetime import datetime
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import feedparser

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
WEBAPP_URL = (os.environ.get("WEBAPP_URL") or "https://nexus-miniapp-8ipk.onrender.com").strip()
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Источники новостей (RSS + публичные Telegram-каналы через веб-превью)
RSS_SOURCES = [
    {"name": "Habr", "category": "Разработка", "url": "https://habr.com/ru/rss/articles/?fl=ru"},
    {"name": "Reddit AI", "category": "ИИ", "url": "https://www.reddit.com/r/artificial/.rss"},
    {"name": "GitHub Blog", "category": "GitHub", "url": "https://github.blog/feed/"},
    {"name": "3DNews", "category": "Железо", "url": "https://3dnews.ru/news/rss/"},
]

TG_CHANNELS = [
    {"name": "TG: Rozetked", "category": "Гаджеты", "username": "rozetked"},
    {"name": "TG: Kod.ru", "category": "Технологии", "username": "kodru"},
]

news_cache = []
last_updated = "Ещё не обновлялось"

def clean_html(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def make_quick_summary(text: str, max_len: int = 190) -> str:
    cleaned = clean_html(text)
    if not cleaned:
        return "Нажмите «Читать оригинал», чтобы открыть полную публикацию."
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[:max_len].rsplit(" ", 1)[0]
    return cut + "..."

async def ai_summarize(title: str, text: str, session: ClientSession) -> str:
    if not GEMINI_API_KEY:
        return make_quick_summary(text)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        f"Сделай очень короткую суть новости на русском языке (1-2 предложения, до 180 символов, без вводных слов).\n"
        f"Заголовок: {title}\nТекст: {clean_html(text)[:1200]}"
    )
    try:
        async with session.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                ans = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if ans:
                    return ans
    except Exception as e:
        logging.warning("Gemini API fallback: %s", e)
    return make_quick_summary(text)

async def fetch_rss_feed(source: dict, session: ClientSession) -> list:
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (NexusAI News Bot)"}
    try:
        async with session.get(source["url"], headers=headers, timeout=12) as resp:
            if resp.status != 200:
                return items
            xml_text = await resp.text()
        feed = feedparser.parse(xml_text)
        for entry in feed.entries[:4]:
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
        logging.warning("Ошибка парсинга %s: %s", source["name"], e)
    return items

async def fetch_tg_channel(channel: dict, session: ClientSession) -> list:
    items = []
    url = f"https://t.me/s/{channel['username']}"
    headers = {"User-Agent": "Mozilla/5.0"}
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
            if len(cleaned) < 30:
                continue
            title = cleaned[:75].rsplit(" ", 1)[0] + "..." if len(cleaned) > 75 else cleaned
            summary = await ai_summarize(title, cleaned, session)
            items.append({
                "title": title,
                "source": channel["name"],
                "category": channel["category"],
                "summary": summary,
                "url": f"https://t.me/{post_id}",
                "time": "Telegram"
            })
    except Exception as e:
        logging.warning("Ошибка парсинга TG %s: %s", channel["username"], e)
    return items

async def refresh_all_news():
    global news_cache, last_updated
    async with ClientSession() as session:
        tasks = [fetch_rss_feed(src, session) for src in RSS_SOURCES]
        tasks += [fetch_tg_channel(ch, session) for ch in TG_CHANNELS]
        results = await asyncio.gather(*tasks)

    combined = []
    # Чередуем источники, чтобы лента была разнообразной
    max_len = max((len(r) for r in results), default=0)
    for i in range(max_len):
        for group in results:
            if i < len(group):
                item = group[i]
                item["id"] = len(combined) + 1
                combined.append(item)

    if combined:
        news_cache = combined
        last_updated = datetime.now().strftime("%H:%M")
        logging.info("Лента обновлена: %d новостей", len(news_cache))

# --- Telegram Bot ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🚀 Открыть NexusAI Ленту",
        web_app=types.WebAppInfo(url=WEBAPP_URL)
    ))
    await message.answer(
        "👋 **NexusAI на связи!**\n\n"
        "Я собираю главные новости из **GitHub, Habr, Reddit и Telegram-каналов** и делаю короткие выжимки.\n\n"
        "Нажми на кнопку ниже, чтобы открыть ленту:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

async def setup_bot_menu():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands([
            types.BotCommand(command="start", description="Открыть главное меню"),
        ])
        if WEBAPP_URL.startswith("https://"):
            menu_button = types.MenuButtonWebApp(
                text="Открыть ленту",
                web_app=types.WebAppInfo(url=WEBAPP_URL)
            )
            await bot.set_chat_menu_button(menu_button=menu_button)
    except Exception as e:
        logging.warning("Меню бота: %s", e)

# --- Web Server (Mini App & Сайт) ---
async def handle_index(request):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>NexusAI — Умная Техно-Лента</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {
                background-color: var(--tg-theme-bg-color, #0b0f19);
                color: var(--tg-theme-text-color, #f3f4f6);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                -webkit-tap-highlight-color: transparent;
            }
            .card-bg {
                background-color: var(--tg-theme-secondary-bg-color, #151c2c);
            }
            .no-scrollbar::-webkit-scrollbar { display: none; }
            .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
        </style>
    </head>
    <body class="pb-16">
        <div class="max-w-lg mx-auto px-4 pt-4">
            <!-- Шапка -->
            <header class="flex justify-between items-center mb-4">
                <div>
                    <div class="flex items-center gap-2">
                        <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
                        <h1 class="text-xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
                            NexusAI Feed
                        </h1>
                    </div>
                    <p id="status-text" class="text-xs text-gray-400 mt-0.5">Загрузка ленты...</p>
                </div>
                <button id="refresh-btn" onclick="forceRefresh()" class="flex items-center gap-1.5 bg-blue-600 active:scale-95 transition hover:bg-blue-500 text-white px-3.5 py-2 rounded-xl text-xs font-semibold shadow-lg shadow-blue-600/20">
                    <span>↻</span> Обновить
                </button>
            </header>

            <!-- Поиск -->
            <div class="mb-3">
                <input id="search-input" oninput="applyFilters()" type="text" placeholder="Поиск по новостям, ИИ, GitHub..."
                    class="w-full card-bg border border-gray-700/70 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-blue-500">
            </div>

            <!-- Категории -->
            <div id="categories" class="flex gap-2 overflow-x-auto no-scrollbar mb-5 pb-1">
                <button onclick="setCategory('Все')" class="cat-btn active px-3.5 py-1.5 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap">Все</button>
                <button onclick="setCategory('ИИ')" class="cat-btn px-3.5 py-1.5 rounded-full text-xs font-semibold card-bg text-gray-300 border border-gray-700/60 whitespace-nowrap">🤖 ИИ</button>
                <button onclick="setCategory('GitHub')" class="cat-btn px-3.5 py-1.5 rounded-full text-xs font-semibold card-bg text-gray-300 border border-gray-700/60 whitespace-nowrap">💻 GitHub</button>
                <button onclick="setCategory('Разработка')" class="cat-btn px-3.5 py-1.5 rounded-full text-xs font-semibold card-bg text-gray-300 border border-gray-700/60 whitespace-nowrap">⚙️ Разработка</button>
                <button onclick="setCategory('Железо')" class="cat-btn px-3.5 py-1.5 rounded-full text-xs font-semibold card-bg text-gray-300 border border-gray-700/60 whitespace-nowrap">🔌 Железо</button>
                <button onclick="setCategory('Гаджеты')" class="cat-btn px-3.5 py-1.5 rounded-full text-xs font-semibold card-bg text-gray-300 border border-gray-700/60 whitespace-nowrap">📱 Гаджеты</button>
            </div>

            <!-- Список новостей -->
            <div id="news-list" class="space-y-3.5"></div>
        </div>

        <script>
            const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
            if (tg) {
                tg.ready();
                tg.expand();
            }

            let allNews = [];
            let currentCategory = 'Все';

            function openExternal(url) {
                if (tg && tg.openLink) {
                    tg.openLink(url);
                } else {
                    window.open(url, '_blank');
                }
            }

            async function loadNews(force = false) {
                const list = document.getElementById('news-list');
                const btn = document.getElementById('refresh-btn');
                btn.disabled = true;
                btn.classList.add('opacity-60');
                if (!allNews.length) {
                    list.innerHTML = '<div class="text-center py-12 text-gray-400 text-sm">Агенты собирают свежие статьи...</div>';
                }

                try {
                    const endpoint = force ? '/api/refresh' : '/api/news';
                    const res = await fetch(endpoint);
                    const data = await res.json();
                    allNews = data.items || [];
                    document.getElementById('status-text').innerText = `Обновлено в ${data.updated} • ${allNews.length} материалов`;
                    applyFilters();
                } catch (e) {
                    list.innerHTML = '<div class="text-center py-10 text-red-400 text-sm">Не удалось загрузить ленту. Попробуйте обновить.</div>';
                } finally {
                    btn.disabled = false;
                    btn.classList.remove('opacity-60');
                }
            }

            function forceRefresh() {
                document.getElementById('status-text').innerText = 'Идёт сбор свежих новостей...';
                loadNews(true);
            }

            function setCategory(cat) {
                currentCategory = cat;
                document.querySelectorAll('.cat-btn').forEach(b => {
                    if (b.innerText.includes(cat)) {
                        b.className = 'cat-btn active px-3.5 py-1.5 rounded-full text-xs font-semibold bg-blue-600 text-white whitespace-nowrap';
                    } else {
                        b.className = 'cat-btn px-3.5 py-1.5 rounded-full text-xs font-semibold card-bg text-gray-300 border border-gray-700/60 whitespace-nowrap';
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
                    list.innerHTML = '<div class="text-center py-10 text-gray-400 text-sm">По вашему фильтру новостей пока нет</div>';
                    return;
                }
                list.innerHTML = '';
                items.forEach(item => {
                    const card = document.createElement('article');
                    card.className = 'card-bg p-4 rounded-2xl border border-gray-700/60 shadow-sm transition';
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-[11px] font-bold px-2.5 py-0.5 rounded-md bg-blue-500/15 text-blue-400 border border-blue-500/20">${item.source}</span>
                            <span class="text-[11px] text-gray-400">${item.category} • ${item.time}</span>
                        </div>
                        <h2 class="font-bold text-base leading-snug text-white mb-2.5">${item.title}</h2>
                        <div class="bg-black/25 p-3 rounded-xl mb-3 border-l-2 border-indigo-500">
                            <div class="text-[11px] font-semibold text-indigo-400 mb-1">⚡ Суть (TL;DR)</div>
                            <p class="text-xs leading-relaxed text-gray-300">${item.summary}</p>
                        </div>
                        <button onclick="openExternal('${item.url}')" class="w-full py-2 rounded-xl bg-gray-800 hover:bg-gray-700 active:scale-[0.99] transition text-xs font-semibold text-gray-200 border border-gray-700/50">
                            Открыть источник ↗
                        </button>
                    `;
                    list.appendChild(card);
                });
            }

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
        await asyncio.sleep(1800)  # Автообновление каждые 30 минут
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
    logging.info("Веб-сервер запущен на порту %s", port)

async def run_bot_polling():
    await asyncio.sleep(3)
    await setup_bot_menu()
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
        except Exception as e:
            logging.error("Polling restart: %s", e)
            await asyncio.sleep(5)

async def main():
    await asyncio.gather(
        start_web_server(),
        periodic_updater(),
        run_bot_polling(),
    )

if __name__ == "__main__":
    asyncio.run(main())
