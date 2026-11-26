import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://nexus-miniapp.onrender.com")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

news_cache = [
    {"id": 1, "title": "Вышел новый фреймворк для ИИ-агентов", "source": "GitHub", "category": "ИИ", "summary": "Упрощает создание мультиагентных систем.", "url": "https://github.com"},
    {"id": 2, "title": "Анонс процессоров нового поколения", "source": "Habr", "category": "Железо", "summary": "Рост производительности на 30%.", "url": "https://habr.com"},
    {"id": 3, "title": "Обсуждение архитектуры LLM на Reddit", "source": "Reddit", "category": "ИИ", "summary": "Разработчики спорят о контекстном окне.", "url": "https://reddit.com"}
]

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🚀 Открыть NexusAI Mini App",
        web_app=types.WebAppInfo(url=WEBAPP_URL)
    ))
    await message.answer(
        "Привет! Я твой ИИ-ассистент по техно-новостям. "
        "Используй кнопку ниже, чтобы открыть умную веб-ленту.",
        reply_markup=builder.as_markup()
    )

async def setup_bot_menu():
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Запустить бота"),
    ])
    menu_button = types.MenuButtonWebApp(text="Открыть ленту", web_app=types.WebAppInfo(url=WEBAPP_URL))
    await bot.set_chat_menu_button(menu_button=menu_button)

async def handle_index(request):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NexusAI Feed</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = { darkMode: 'class' };
            if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.colorScheme === 'dark') {
                document.documentElement.classList.add('dark');
            }
        </script>
        <style>
            body {
                background-color: var(--tg-theme-bg-color, #111827);
                color: var(--tg-theme-text-color, #ffffff);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            }
            .card-bg { background-color: var(--tg-theme-secondary-bg-color, #1f2937); }
        </style>
    </head>
    <body class="pb-20">
        <div id="app" class="max-w-md mx-auto px-4 pt-4">
            <header class="flex justify-between items-center mb-6">
                <h1 class="text-2xl font-bold">NexusAI Техно-Лента</h1>
                <button onclick="fetchNews()" class="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-full text-xs font-semibold">Обновить</button>
            </header>
            <div id="news-list" class="space-y-4"></div>
        </div>

        <script>
            const tg = window.Telegram.WebApp;
            tg.ready();
            tg.expand();

            async function fetchNews() {
                const list = document.getElementById('news-list');
                list.innerHTML = '<p class="text-center py-4">Сбор свежих данных...</p>';
                try {
                    const response = await fetch('/api/news');
                    const data = await response.json();
                    renderNews(data);
                } catch (e) {
                    list.innerHTML = '<p class="text-center text-red-500 py-4">Ошибка загрузки</p>';
                }
            }

            function renderNews(news) {
                const list = document.getElementById('news-list');
                list.innerHTML = '';
                news.forEach(item => {
                    const card = document.createElement('div');
                    card.className = 'card-bg p-4 rounded-xl shadow-md border border-gray-700';
                    card.innerHTML = `
                        <div class="flex justify-between items-start mb-2">
                            <span class="text-xs font-bold px-2 py-0.5 rounded bg-blue-900 text-blue-200">${item.source}</span>
                            <span class="text-xs text-gray-400 font-medium">${item.category}</span>
                        </div>
                        <h2 class="font-bold text-lg mb-2">${item.title}</h2>
                        <div class="bg-black/20 p-2.5 rounded-lg mb-3 border-l-2 border-blue-500">
                            <p class="text-xs font-semibold text-blue-400 mb-1">⚡ ИИ-выжимка TL;DR:</p>
                            <p class="text-sm text-gray-200">${item.summary}</p>
                        </div>
                        <button onclick="tg.openLink('${item.url}')" class="w-full text-center bg-gray-700 hover:bg-gray-600 text-white py-1.5 rounded-lg text-xs font-medium">Читать оригинал</button>
                    `;
                    list.appendChild(card);
                });
            }

            fetchNews();
        </script>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')

async def handle_api_news(request):
    return web.json_response(news_cache)

async def start_web_server():
    app = web.Application()
    app.add_routes([web.get('/', handle_index), web.get('/api/news', handle_api_news)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await setup_bot_menu()
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == '__main__':
    asyncio.run(main())
