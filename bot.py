import os
import sqlite3
import asyncio
import signal
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters, ContextTypes)
from telegram.error import TimedOut, NetworkError, RetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from gtts import gTTS
import pytz

from words_data import WORDS_DATABASE

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Глобальные переменные
check_sessions = {}
application = None
word_scheduler = None
bio_scheduler = None
is_running = True
reconnect_attempt = 0
MAX_RECONNECT_ATTEMPTS = 100
BASE_RECONNECT_DELAY = 5

TEMP_DIR = "temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)


# ===== КЛАВИАТУРЫ =====

def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📚 Мои слова", callback_data="my_words"),
            InlineKeyboardButton("📊 Статистика", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("🔊 Прослушать слово", callback_data="listen_word"),
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ],
        [
            InlineKeyboardButton("📢 Подписаться", callback_data="subscribe"),
            InlineKeyboardButton("🔕 Отписаться", callback_data="unsubscribe")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📚 Мои слова", callback_data="my_words"),
            InlineKeyboardButton("📊 Статистика", callback_data="my_stats")
        ],
        [
            InlineKeyboardButton("🔊 Прослушать слово", callback_data="listen_word"),
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ],
        [
            InlineKeyboardButton("📢 Подписаться", callback_data="subscribe"),
            InlineKeyboardButton("🔕 Отписаться", callback_data="unsubscribe")
        ],
        [
            InlineKeyboardButton("👥 Статистика бота", callback_data="bot_stats"),
            InlineKeyboardButton("📈 Админ-панель", callback_data="admin_panel")
        ],
        [
            InlineKeyboardButton("👤 Все пользователи", callback_data="all_users"),
            InlineKeyboardButton("🟢 Активные", callback_data="active_users")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]])


def get_users_navigation_keyboard(page, total_pages, prefix):
    keyboard = []
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f"{prefix}_page_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("След. ➡️", callback_data=f"{prefix}_page_{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


# ===== БЕЗОПАСНАЯ ОТПРАВКА =====

async def safe_send_message(bot, chat_id, text, parse_mode='HTML', reply_markup=None, max_retries=5):
    for attempt in range(max_retries):
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError):
            if attempt < max_retries - 1:
                delay = 2 * (attempt + 1)
                print(f"⚠️ Таймаут отправки. Повтор через {delay}с...")
                await asyncio.sleep(delay)
        except RetryAfter as error:
            delay = min(error.retry_after, 30)
            print(f"⏳ Ожидание {delay}с...")
            await asyncio.sleep(delay)
        except Exception as error:
            print(f"❌ Ошибка отправки: {error}")
            break
    return None


async def safe_edit_message(message, text, parse_mode='HTML', reply_markup=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await message.edit_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError):
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
        except Exception:
            break
    return None


# ===== АУДИО =====

def get_word_audio(word):
    try:
        audio_file = os.path.join(TEMP_DIR, f"{word}.mp3")
        if not os.path.exists(audio_file):
            tts = gTTS(text=word, lang='en', slow=False)
            tts.save(audio_file)
        return audio_file
    except Exception as error:
        print(f"Ошибка аудио для '{word}': {error}")
        return None


# ===== БАЗА ДАННЫХ =====

def init_db():
    connection = sqlite3.connect('english_words.db')
    cursor = connection.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            transcription TEXT NOT NULL,
            translation TEXT NOT NULL,
            UNIQUE(word, translation)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subscribed BOOLEAN DEFAULT 1,
            total_checks INTEGER DEFAULT 0,
            total_learned INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learned_words (
            user_id INTEGER, word_id INTEGER,
            learned_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (word_id) REFERENCES words (id),
            PRIMARY KEY (user_id, word_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_words (
            user_id INTEGER, word_id INTEGER, date DATE,
            sent_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            answered BOOLEAN DEFAULT 0, correct BOOLEAN,
            FOREIGN KEY (word_id) REFERENCES words (id),
            PRIMARY KEY (user_id, word_id, date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mistakes (
            user_id INTEGER, word_id INTEGER, mistake_date DATE,
            attempts INTEGER DEFAULT 1,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            corrected BOOLEAN DEFAULT 0,
            FOREIGN KEY (word_id) REFERENCES words (id),
            PRIMARY KEY (user_id, word_id, mistake_date)
        )
    ''')

    connection.commit()

    for col in ['first_name', 'last_name', 'total_checks', 'total_learned']:
        try:
            if col in ['first_name', 'last_name']:
                cursor.execute(f'ALTER TABLE users ADD COLUMN {col} TEXT')
            else:
                cursor.execute(f'ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
    connection.commit()

    # Чиним битые записи
    try:
        cursor.execute("UPDATE words SET translation = 'перевод' WHERE translation IS NULL OR translation = ''")
        cursor.execute("UPDATE words SET word = 'unknown' WHERE word IS NULL OR word = ''")
        connection.commit()
    except sqlite3.OperationalError:
        pass

    cursor.execute('SELECT COUNT(*) FROM words')
    count = cursor.fetchone()[0]

    if count < len(WORDS_DATABASE):
        print(f"📚 Загрузка слов... (текущее: {count})")
        existing = set()
        
        try:
            cursor.execute('SELECT word, translation FROM words')
            rows = cursor.fetchall()
            for row in rows:
                if row and len(row) >= 2:
                    word_val = row[0] if row[0] else ""
                    trans_val = row[1] if row[1] else ""
                    existing.add((word_val, trans_val))
        except Exception as e:
            print(f"⚠️ Пропуск проверки дубликатов: {e}")

        new_words = [w for w in WORDS_DATABASE if (w[0], w[2]) not in existing]
        if new_words:
            for i in range(0, len(new_words), 500):
                cursor.executemany(
                    'INSERT OR IGNORE INTO words (word, transcription, translation) VALUES (?, ?, ?)',
                    new_words[i:i + 500]
                )
            connection.commit()
            print(f"✅ Добавлено {len(new_words)} новых слов")

    cursor.execute('SELECT COUNT(*) FROM words')
    print(f"📊 Слов в базе: {cursor.fetchone()[0]}")
    connection.close()


def get_db_connection():
    try:
        return sqlite3.connect('english_words.db')
    except sqlite3.Error:
        return None


def add_user(user_id, username=None, first_name=None, last_name=None):
    connection = get_db_connection()
    if connection:
        connection.execute(
            'INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_active, subscribed) '
            'VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 1)',
            (user_id, username, first_name, last_name)
        )
        connection.commit()
        connection.close()


def get_all_subscribed_users():
    connection = get_db_connection()
    if connection:
        users = connection.execute('SELECT user_id FROM users WHERE subscribed = 1').fetchall()
        connection.close()
        return [u[0] for u in users]
    return []


def get_all_users(page=1, per_page=10):
    connection = get_db_connection()
    if connection:
        total = connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        offset = (page - 1) * per_page
        users = connection.execute(
            'SELECT user_id, username, first_name, last_name, subscribed, '
            'first_seen, last_active, total_checks, total_learned '
            'FROM users ORDER BY first_seen DESC LIMIT ? OFFSET ?',
            (per_page, offset)
        ).fetchall()
        connection.close()
        return users, total
    return [], 0


def get_active_users(days=7, page=1, per_page=10):
    connection = get_db_connection()
    if connection:
        total = connection.execute(
            f"SELECT COUNT(DISTINCT user_id) FROM users "
            f"WHERE last_active >= datetime('now', '-{days} days')"
        ).fetchone()[0]
        offset = (page - 1) * per_page
        users = connection.execute(
            f'SELECT u.user_id, u.username, u.first_name, u.last_name, u.subscribed, '
            f'u.first_seen, u.last_active, u.total_checks, u.total_learned, '
            f'COUNT(dw.word_id) as words_today '
            f'FROM users u LEFT JOIN daily_words dw ON u.user_id = dw.user_id AND dw.date = date(\'now\') '
            f'WHERE u.last_active >= datetime(\'now\', \'-{days} days\') '
            f'GROUP BY u.user_id ORDER BY u.last_active DESC LIMIT ? OFFSET ?',
            (per_page, offset)
        ).fetchall()
        connection.close()
        return users, total
    return [], 0


def get_random_words_for_user(user_id, count=5):
    connection = get_db_connection()
    if connection:
        words = connection.execute(
            'SELECT w.id, w.word, w.transcription, w.translation '
            'FROM words w '
            'WHERE w.id NOT IN (SELECT word_id FROM learned_words WHERE user_id = ?) '
            'ORDER BY RANDOM() LIMIT ?',
            (user_id, count)
        ).fetchall()
        connection.close()
        return words
    return []


def get_mistake_words(user_id, count=5):
    connection = get_db_connection()
    if connection:
        words = connection.execute(
            'SELECT w.id, w.word, w.transcription, w.translation '
            'FROM words w JOIN mistakes m ON w.id = m.word_id '
            'WHERE m.user_id = ? AND m.corrected = 0 '
            'ORDER BY m.last_attempt DESC LIMIT ?',
            (user_id, count)
        ).fetchall()
        connection.close()
        return words
    return []


def save_daily_words(user_id, word_ids):
    connection = get_db_connection()
    if connection:
        today = datetime.now().strftime('%Y-%m-%d')
        for word_id in word_ids:
            connection.execute(
                'INSERT OR IGNORE INTO daily_words (user_id, word_id, date) VALUES (?, ?, ?)',
                (user_id, word_id, today)
            )
        connection.commit()
        connection.close()


def mark_word_learned(user_id, word_id):
    connection = get_db_connection()
    if connection:
        connection.execute(
            'INSERT OR IGNORE INTO learned_words (user_id, word_id) VALUES (?, ?)',
            (user_id, word_id)
        )
        connection.execute(
            'UPDATE mistakes SET corrected = 1 WHERE user_id = ? AND word_id = ?',
            (user_id, word_id)
        )
        connection.execute(
            'UPDATE users SET total_learned = '
            '(SELECT COUNT(*) FROM learned_words WHERE user_id = ?) WHERE user_id = ?',
            (user_id, user_id)
        )
        connection.commit()
        connection.close()


def add_mistake(user_id, word_id):
    connection = get_db_connection()
    if connection:
        today = datetime.now().strftime('%Y-%m-%d')
        result = connection.execute(
            'SELECT attempts FROM mistakes WHERE user_id = ? AND word_id = ? AND mistake_date = ?',
            (user_id, word_id, today)
        ).fetchone()
        if result:
            connection.execute(
                'UPDATE mistakes SET attempts = attempts + 1, last_attempt = CURRENT_TIMESTAMP '
                'WHERE user_id = ? AND word_id = ? AND mistake_date = ?',
                (user_id, word_id, today)
            )
        else:
            connection.execute(
                'INSERT INTO mistakes (user_id, word_id, mistake_date) VALUES (?, ?, ?)',
                (user_id, word_id, today)
            )
        connection.execute(
            'UPDATE users SET total_checks = total_checks + 1 WHERE user_id = ?',
            (user_id,)
        )
        connection.commit()
        connection.close()


def get_learned_words(user_id):
    connection = get_db_connection()
    if connection:
        words = connection.execute(
            'SELECT w.word, w.transcription, w.translation, lw.learned_date '
            'FROM words w JOIN learned_words lw ON w.id = lw.word_id '
            'WHERE lw.user_id = ? ORDER BY lw.learned_date DESC',
            (user_id,)
        ).fetchall()
        connection.close()
        return words
    return []


def get_today_words(user_id):
    connection = get_db_connection()
    if connection:
        today = datetime.now().strftime('%Y-%m-%d')
        words = connection.execute(
            'SELECT w.id, w.word, w.transcription, w.translation '
            'FROM words w JOIN daily_words dw ON w.id = dw.word_id '
            'WHERE dw.user_id = ? AND dw.date = ?',
            (user_id, today)
        ).fetchall()
        connection.close()
        return words
    return []


def get_word_count():
    connection = get_db_connection()
    if connection:
        count = connection.execute('SELECT COUNT(*) FROM words').fetchone()[0]
        connection.close()
        return count
    return 0


def get_user_stats(user_id):
    connection = get_db_connection()
    if connection:
        learned = connection.execute(
            'SELECT COUNT(*) FROM learned_words WHERE user_id = ?', (user_id,)
        ).fetchone()[0]
        mistakes = connection.execute(
            'SELECT COUNT(DISTINCT word_id) FROM mistakes WHERE user_id = ? AND corrected = 0',
            (user_id,)
        ).fetchone()[0]
        connection.close()
        return learned, mistakes
    return 0, 0


def get_subscriber_count():
    connection = get_db_connection()
    if connection:
        count = connection.execute('SELECT COUNT(*) FROM users WHERE subscribed = 1').fetchone()[0]
        connection.close()
        return count
    return 0


def get_total_users():
    connection = get_db_connection()
    if connection:
        count = connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        connection.close()
        return count
    return 0


def get_active_users_today():
    connection = get_db_connection()
    if connection:
        today = datetime.now().strftime('%Y-%m-%d')
        count = connection.execute(
            'SELECT COUNT(DISTINCT user_id) FROM daily_words WHERE date = ?', (today,)
        ).fetchone()[0]
        connection.close()
        return count
    return 0


def get_subscribers_growth():
    connection = get_db_connection()
    if connection:
        growth = connection.execute(
            'SELECT DATE(first_seen) as date, COUNT(*) as count '
            'FROM users GROUP BY DATE(first_seen) ORDER BY date DESC LIMIT 30'
        ).fetchall()
        connection.close()
        return growth
    return []


def get_top_users():
    connection = get_db_connection()
    if connection:
        users = connection.execute(
            'SELECT u.user_id, u.username, COUNT(lw.word_id) as learned_count '
            'FROM users u LEFT JOIN learned_words lw ON u.user_id = lw.user_id '
            'GROUP BY u.user_id ORDER BY learned_count DESC LIMIT 10'
        ).fetchall()
        connection.close()
        return users
    return []


def subscribe_user(user_id):
    connection = get_db_connection()
    if connection:
        connection.execute('UPDATE users SET subscribed = 1 WHERE user_id = ?', (user_id,))
        connection.commit()
        connection.close()


def unsubscribe_user(user_id):
    connection = get_db_connection()
    if connection:
        connection.execute('UPDATE users SET subscribed = 0 WHERE user_id = ?', (user_id,))
        connection.commit()
        connection.close()


def is_subscribed(user_id):
    connection = get_db_connection()
    if connection:
        result = connection.execute(
            'SELECT subscribed FROM users WHERE user_id = ?', (user_id,)
        ).fetchone()
        connection.close()
        return result and result[0] == 1
    return False


def is_admin(user_id):
    return user_id == int(os.getenv('ADMIN_ID', '0'))


# ===== ОБНОВЛЕНИЕ ОПИСАНИЯ БОТА =====

async def update_bot_bio(context):
    try:
        bot = context.bot if hasattr(context, 'bot') else context.application.bot
        count = get_subscriber_count()
        description = f"👥 {count} учеников"
        try:
            await bot.set_my_description(description)
        except Exception:
            pass
    except Exception:
        pass


async def update_bot_bio_wrapper(context: ContextTypes.DEFAULT_TYPE):
    await update_bot_bio(context)


def setup_bio_update_scheduler(app):
    scheduler = AsyncIOScheduler(timezone=pytz.UTC)
    scheduler.add_job(update_bot_bio_wrapper, 'interval', hours=6, args=[app])
    scheduler.start()
    return scheduler


# ===== УВЕДОМЛЕНИЯ =====

async def notify_admin_new_subscriber(context, user_id, username):
    admin_id = int(os.getenv('ADMIN_ID', '0'))
    if admin_id and admin_id != user_id:
        await safe_send_message(
            context.bot, admin_id,
            f"🆕 <b>Новый подписчик!</b>\n\n"
            f"ID: <code>{user_id}</code>\n"
            f"Username: @{username or 'не указан'}\n"
            f"Всего: <b>{get_subscriber_count()}</b>"
        )


# ===== ОТПРАВКА СЛОВ =====

async def send_words_to_user(context, user_id):
    try:
        mistake_words = get_mistake_words(user_id, 5)
        new_count = max(0, 5 - len(mistake_words))
        new_words = get_random_words_for_user(user_id, new_count) if new_count > 0 else []
        all_words = mistake_words + new_words

        if not all_words:
            keyboard = get_admin_keyboard() if is_admin(user_id) else get_main_keyboard()
            await safe_send_message(context.bot, user_id, "🎉 Вы выучили все слова!", reply_markup=keyboard)
            return

        save_daily_words(user_id, [w[0] for w in all_words])

        msg = "📚 <b>Слова на сегодня:</b>\n\n"
        if mistake_words:
            msg += "🔄 <i>Повторение:</i>\n"
        for i, w in enumerate(all_words, 1):
            if i == len(mistake_words) + 1 and mistake_words:
                msg += "\n✨ <i>Новые:</i>\n"
            msg += f"{i}. <b>{w[1]}</b> {w[2]} - <i>{w[3]}</i>\n"
        msg += "\n📝 <i>Проверка в 20:00</i>"

        keyboard = get_admin_keyboard() if is_admin(user_id) else get_main_keyboard()
        await safe_send_message(context.bot, user_id, msg, reply_markup=keyboard)

        for w in all_words[len(mistake_words):]:
            audio = get_word_audio(w[1])
            if audio and os.path.exists(audio):
                with open(audio, 'rb') as file:
                    try:
                        await context.bot.send_audio(
                            user_id, file,
                            caption=f"🔊 <b>{w[1]}</b> - {w[3]}",
                            parse_mode='HTML',
                            title=w[1]
                        )
                    except Exception:
                        pass
            await asyncio.sleep(0.3)
    except Exception as error:
        print(f"Ошибка отправки {user_id}: {error}")


# ===== ОБРАБОТЧИКИ =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(
        user_id,
        update.effective_user.username,
        update.effective_user.first_name,
        update.effective_user.last_name
    )
    await notify_admin_new_subscriber(context, user_id, update.effective_user.username)

    keyboard = get_admin_keyboard() if is_admin(user_id) else get_main_keyboard()
    await safe_send_message(
        context.bot, update.effective_chat.id,
        f"👋 <b>English Learning Bot!</b>\n\n"
        f"📚 Слов: <b>{get_word_count()}</b>\n"
        f"👥 Пользователей: <b>{get_subscriber_count()}</b>\n\n"
        f"Используйте кнопки 👇",
        reply_markup=keyboard
    )

    await send_words_to_user(context, user_id)
    await update_bot_bio(context)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id, data = query.from_user.id, query.data

    if data.startswith("all_users_page_"):
        await show_all_users_page(query, user_id, int(data.replace("all_users_page_", "")))
    elif data.startswith("active_users_page_"):
        await show_active_users_page(query, user_id, int(data.replace("active_users_page_", "")))
    elif data == "my_words":
        words = get_learned_words(user_id)
        if words:
            msg = f"📚 <b>Выученные слова</b> ({len(words)}/{get_word_count()}):\n\n"
            for i, w in enumerate(words[:20], 1):
                msg += f"{i}. <b>{w[0]}</b> {w[1]} - <i>{w[2]}</i>\n"
            if len(words) > 20:
                msg += f"\n<i>...и еще {len(words) - 20}</i>"
        else:
            msg = "📭 Нет выученных слов"
        await safe_edit_message(query.message, msg, reply_markup=get_back_keyboard())
    elif data == "my_stats":
        learned, mistakes = get_user_stats(user_id)
        total = get_word_count()
        percentage = (learned / total * 100) if total > 0 else 0
        bar = '🟢' * int(percentage // 10) + '⚪' * (10 - int(percentage // 10))
        await safe_edit_message(
            query.message,
            f"📊 <b>Статистика</b>\n\n"
            f"📚 Всего: <b>{total}</b>\n"
            f"✅ Выучено: <b>{learned}</b> ({percentage:.1f}%)\n"
            f"❌ На повторении: <b>{mistakes}</b>\n"
            f"📈 {bar}",
            reply_markup=get_back_keyboard()
        )
    elif data == "listen_word":
        await safe_edit_message(
            query.message,
            "🔊 Используйте: <code>/listen apple</code>",
            reply_markup=get_back_keyboard()
        )
    elif data == "help":
        await safe_edit_message(
            query.message,
            "📖 <b>Бот:</b>\n9:10 - слова\n20:00 - проверка\n"
            "Ошибки повторяются\n\n💡 Отвечайте в нижнем регистре",
            reply_markup=get_back_keyboard()
        )
    elif data == "subscribe":
        if is_subscribed(user_id):
            await safe_edit_message(query.message, "✅ Уже подписаны!", reply_markup=get_back_keyboard())
        else:
            subscribe_user(user_id)
            await update_bot_bio(context)
            keyboard = get_admin_keyboard() if is_admin(user_id) else get_main_keyboard()
            await safe_edit_message(query.message, "✅ <b>Подписались!</b>", reply_markup=keyboard)
    elif data == "unsubscribe":
        if not is_subscribed(user_id):
            await safe_edit_message(query.message, "❌ Не подписаны", reply_markup=get_back_keyboard())
        else:
            unsubscribe_user(user_id)
            await update_bot_bio(context)
            await safe_edit_message(query.message, "👋 <b>Отписались</b>", reply_markup=get_back_keyboard())
    elif data == "bot_stats":
        if not is_admin(user_id):
            await query.answer("⛔ Доступ запрещен", show_alert=True)
        else:
            await safe_edit_message(
                query.message,
                f"📊 <b>Статистика</b>\n\n"
                f"👥 Всего: <b>{get_total_users()}</b>\n"
                f"✅ Подписчики: <b>{get_subscriber_count()}</b>\n"
                f"📅 Сегодня: <b>{get_active_users_today()}</b>\n"
                f"📚 Слов: <b>{get_word_count()}</b>",
                reply_markup=get_back_keyboard()
            )
    elif data == "admin_panel":
        if not is_admin(user_id):
            await query.answer("⛔ Доступ запрещен", show_alert=True)
        else:
            growth = get_subscribers_growth()
            top = get_top_users()
            msg = (
                f"📊 <b>Админ-панель</b>\n\n"
                f"👥 Всего: <b>{get_total_users()}</b>\n"
                f"✅ Подписчики: <b>{get_subscriber_count()}</b>\n"
                f"📅 Сегодня: <b>{get_active_users_today()}</b>\n"
                f"📚 Слов: <b>{get_word_count()}</b>\n\n"
                f"<b>🏆 Топ-10:</b>\n"
            )
            for i, u in enumerate(top, 1):
                msg += f"{i}. @{u[1] or f'user{u[0]}'}: <b>{u[2]}</b> слов\n"
            if growth:
                msg += "\n<b>📈 Рост (7 дн):</b>\n"
                for date, cnt in growth[:7]:
                    msg += f"{date}: +{cnt}\n"
            await safe_edit_message(query.message, msg, reply_markup=get_back_keyboard())
    elif data == "all_users":
        await show_all_users_page(query, user_id, 1)
    elif data == "active_users":
        await show_active_users_page(query, user_id, 1)
    elif data == "back_to_main":
        keyboard = get_admin_keyboard() if is_admin(user_id) else get_main_keyboard()
        await safe_edit_message(query.message, "📚 <b>Главное меню</b>", reply_markup=keyboard)


def format_user_info(user):
    uid, username, first_name, last_name, subscribed, first_seen, last_active, total_checks, total_learned = user[:9]
    name = " ".join([n for n in [first_name, last_name] if n]) or "Не указано"
    status = "🟢" if subscribed else "🔴"
    username_str = f"@{username}" if username else "нет username"
    return (
        f"{status} <b>{name}</b>\n"
        f"   ID: <code>{uid}</code>\n"
        f"   Username: {username_str}\n"
        f"   Вход: {first_seen[:10] if first_seen else 'Н/Д'}\n"
        f"   Активность: {last_active[:10] if last_active else 'Н/Д'}\n"
        f"   Проверок: {total_checks or 0} | Выучено: {total_learned or 0}"
    )


async def show_all_users_page(query, user_id, page=1):
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен", show_alert=True)
        return
    users, total = get_all_users(page, 5)
    if not users:
        await safe_edit_message(query.message, "📭 Нет пользователей", reply_markup=get_back_keyboard())
        return
    total_pages = max(1, (total + 4) // 5)
    msg = f"<b>👥 Все пользователи</b>\n📊 Всего: <b>{total}</b> | {page}/{total_pages}\n\n"
    for u in users:
        msg += format_user_info(u) + "\n"
    await safe_edit_message(
        query.message, msg,
        reply_markup=get_users_navigation_keyboard(page, total_pages, "all_users")
    )


async def show_active_users_page(query, user_id, page=1):
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен", show_alert=True)
        return
    users, total = get_active_users(7, page, 5)
    if not users:
        await safe_edit_message(query.message, "📭 Нет активных за 7 дней", reply_markup=get_back_keyboard())
        return
    total_pages = max(1, (total + 4) // 5)
    msg = f"<b>🟢 Активные (7 дн)</b>\n📊 Всего: <b>{total}</b> | {page}/{total_pages}\n\n"
    for u in users:
        uid_val, uname, f_name, l_name, sub, f_seen, l_active, t_checks, t_learned, w_today = u
        name = " ".join([n for n in [f_name, l_name] if n]) or "Не указано"
        status = "🟢" if sub else "🔴"
        uname_str = f"@{uname}" if uname else "нет username"
        msg += (
            f"{status} <b>{name}</b>\n"
            f"   ID: <code>{uid_val}</code>\n"
            f"   Username: {uname_str}\n"
            f"   Слов сегодня: {w_today or 0}\n"
            f"   Проверок: {t_checks or 0} | Выучено: {t_learned or 0}\n\n"
        )
    await safe_edit_message(
        query.message, msg,
        reply_markup=get_users_navigation_keyboard(page, total_pages, "active_users")
    )


# ===== КОМАНДЫ =====

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = get_admin_keyboard() if is_admin(update.effective_user.id) else get_main_keyboard()
    await safe_send_message(
        context.bot, update.effective_chat.id,
        "📖 Используйте кнопки или команды:\n/words, /stats, /listen",
        reply_markup=keyboard
    )


async def listen_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_send_message(context.bot, update.effective_chat.id, "❌ /listen apple")
        return
    word = ' '.join(context.args).lower()
    audio = get_word_audio(word)
    if audio and os.path.exists(audio):
        with open(audio, 'rb') as file:
            await context.bot.send_audio(
                update.effective_chat.id, file,
                caption=f"🔊 <b>{word}</b>",
                parse_mode='HTML',
                title=word
            )
    else:
        await safe_send_message(
            context.bot, update.effective_chat.id,
            f"❌ Не удалось создать аудио для <b>{word}</b>"
        )


async def show_learned_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words = get_learned_words(update.effective_user.id)
    if not words:
        await safe_send_message(context.bot, update.effective_chat.id, "📭 Нет выученных слов")
        return
    msg = f"📚 <b>Выученные слова</b> ({len(words)}/{get_word_count()}):\n\n"
    for i, w in enumerate(words[:20], 1):
        msg += f"{i}. <b>{w[0]}</b> {w[1]} - <i>{w[2]}</i>\n"
    await safe_send_message(context.bot, update.effective_chat.id, msg)


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    learned, mistakes = get_user_stats(update.effective_user.id)
    total = get_word_count()
    percentage = (learned / total * 100) if total > 0 else 0
    bar = '🟢' * int(percentage // 10) + '⚪' * (10 - int(percentage // 10))
    await safe_send_message(
        context.bot, update.effective_chat.id,
        f"📊 <b>Статистика</b>\n\n"
        f"📚 Всего: <b>{total}</b>\n"
        f"✅ Выучено: <b>{learned}</b> ({percentage:.1f}%)\n"
        f"❌ На повторении: <b>{mistakes}</b>\n"
        f"📈 {bar}"
    )


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_subscribed(user_id):
        await safe_send_message(context.bot, update.effective_chat.id, "✅ Уже подписаны!")
    else:
        subscribe_user(user_id)
        await update_bot_bio(context)
        await safe_send_message(context.bot, update.effective_chat.id, "✅ <b>Подписались!</b>")


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_subscribed(user_id):
        await safe_send_message(context.bot, update.effective_chat.id, "❌ Не подписаны")
    else:
        unsubscribe_user(user_id)
        await update_bot_bio(context)
        await safe_send_message(context.bot, update.effective_chat.id, "👋 <b>Отписались!</b>")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await safe_send_message(context.bot, update.effective_chat.id, "⛔ Доступ запрещен")
        return
    users, total = get_all_users(1, 10)
    if not users:
        await safe_send_message(context.bot, update.effective_chat.id, "📭 Нет пользователей")
        return
    msg = f"<b>👥 Все пользователи</b>\n📊 Всего: <b>{total}</b>\n\n"
    for u in users[:10]:
        msg += format_user_info(u) + "\n"
    await safe_send_message(context.bot, update.effective_chat.id, msg)


# ===== ПРОВЕРКА =====

async def start_check_for_user(context, user_id):
    words = get_today_words(user_id)
    if not words:
        await safe_send_message(context.bot, user_id, "📝 Сегодня нет слов для проверки")
        return
    check_sessions[user_id] = {'words': words, 'current_index': 0, 'answers': {}}
    await safe_send_message(
        context.bot, user_id,
        f"📝 <b>Проверка!</b>\n\n"
        f"Напишите перевод:\n\n"
        f"<b>{words[0][1]}</b> [{words[0][2]}]\n\n"
        f"Слово 1 из {len(words)}"
    )


async def process_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in check_sessions:
        return
    session = check_sessions[user_id]
    answer = update.message.text.strip().lower()
    idx = session['current_index']
    words = session['words']
    if idx >= len(words):
        return
    word = words[idx]
    correct = word[3].lower() == answer
    session['answers'][word[0]] = {
        'word': word[1],
        'transcription': word[2],
        'correct_translation': word[3],
        'user_answer': answer,
        'is_correct': correct
    }

    if correct:
        await safe_send_message(context.bot, update.effective_chat.id, "✅ Правильно!")
    else:
        await safe_send_message(
            context.bot, update.effective_chat.id,
            f"❌ Неправильно!\nПравильно: <b>{word[3]}</b>"
        )

    session['current_index'] += 1
    if session['current_index'] < len(words):
        next_word = words[session['current_index']]
        await safe_send_message(
            context.bot, update.effective_chat.id,
            f"Слово {session['current_index'] + 1} из {len(words)}:\n\n"
            f"<b>{next_word[1]}</b> [{next_word[2]}]"
        )
    else:
        await finish_check(update, context, user_id)


async def finish_check(update, context, user_id):
    session = check_sessions[user_id]
    answers = session['answers']
    correct_count = sum(1 for a in answers.values() if a['is_correct'])
    total = len(answers)

    for word_id, answer_item in answers.items():
        if answer_item['is_correct']:
            mark_word_learned(user_id, word_id)
        else:
            add_mistake(user_id, word_id)

    percentage = (correct_count / total * 100) if total > 0 else 0

    if percentage == 100:
        emoji, comment = "🎉", "Великолепно!"
    elif percentage >= 80:
        emoji, comment = "👍", "Отлично!"
    elif percentage >= 60:
        emoji, comment = "📚", "Хорошо!"
    elif percentage >= 40:
        emoji, comment = "💪", "Старайтесь!"
    else:
        emoji, comment = "📖", "Практикуйтесь!"

    msg = (
        f"{emoji} <b>Результаты</b>\n\n"
        f"✅ Правильно: <b>{correct_count}</b> из <b>{total}</b>\n"
        f"📊 {percentage:.0f}%\n\n"
        f"<i>{comment}</i>\n\n"
    )

    incorrect = {k: v for k, v in answers.items() if not v['is_correct']}
    if incorrect:
        msg += "❌ <b>Ошибки:</b>\n\n"
        for __, ans in incorrect.items():
            msg += (
                f"• <b>{ans['word']}</b> {ans['transcription']}\n"
                f"  Правильно: <i>{ans['correct_translation']}</i>\n"
                f"  Ваш ответ: {ans['user_answer']}\n\n"
            )
        msg += "🔄 Эти слова будут повторены."

    keyboard = get_admin_keyboard() if is_admin(user_id) else get_main_keyboard()
    await safe_send_message(context.bot, update.effective_chat.id, msg, reply_markup=keyboard)
    del check_sessions[user_id]


# ===== РАСПИСАНИЕ =====

async def scheduled_morning_words(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_subscribed_users()
    print(f"📚 Отправка слов {len(users)} пользователям...")
    for uid in users:
        try:
            await send_words_to_user(context, uid)
        except Exception as error:
            print(f"Ошибка {uid}: {error}")


async def scheduled_evening_check(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_subscribed_users()
    print(f"📝 Проверка для {len(users)} пользователей...")
    for uid in users:
        try:
            await start_check_for_user(context, uid)
        except Exception as error:
            print(f"Ошибка {uid}: {error}")


def setup_scheduler(app):
    scheduler = AsyncIOScheduler(timezone=pytz.UTC)
    scheduler.add_job(scheduled_morning_words, 'cron', hour=6, minute=10, args=[app])
    scheduler.add_job(scheduled_evening_check, 'cron', hour=17, minute=0, args=[app])
    scheduler.start()
    print("⏰ Планировщик запущен")
    return scheduler


# ===== СИСТЕМА АВТОМАТИЧЕСКОГО ПЕРЕПОДКЛЮЧЕНИЯ =====

async def check_connection(bot):
    try:
        await bot.get_me()
        return True
    except (TimedOut, NetworkError):
        return False
    except Exception:
        return False


async def reconnect_bot(app):
    global reconnect_attempt, is_running

    while is_running:
        try:
            if await check_connection(app.bot):
                reconnect_attempt = 0
                return True

            reconnect_attempt += 1
            if reconnect_attempt > MAX_RECONNECT_ATTEMPTS:
                print(f"❌ Превышено максимальное количество попыток ({MAX_RECONNECT_ATTEMPTS})")
                return False

            delay = min(BASE_RECONNECT_DELAY * reconnect_attempt, 300)
            print(f"🔌 Потеря связи. Попытка переподключения {reconnect_attempt}/{MAX_RECONNECT_ATTEMPTS} через {delay}с...")

            await asyncio.sleep(delay)

            try:
                await app.updater.stop()
                await app.stop()
            except Exception:
                pass

            try:
                await app.initialize()
                await app.start()
                await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            except Exception as error:
                print(f"⚠️ Ошибка переподключения: {error}")

        except Exception as error:
            print(f"❌ Критическая ошибка: {error}")
            await asyncio.sleep(10)


async def connection_watchdog(app):
    global is_running

    print("🔄 Система автоматического переподключения активирована")

    while is_running:
        try:
            connected = await check_connection(app.bot)

            if not connected:
                print("🔴 Соединение потеряно. Запуск переподключения...")
                success = await reconnect_bot(app)

                if success:
                    print("🟢 Соединение восстановлено!")
                else:
                    print("❌ Не удалось восстановить соединение")
                    is_running = False
                    break
        except Exception as error:
            print(f"❌ Ошибка в системе мониторинга: {error}")

        await asyncio.sleep(30)


# ===== ОБРАБОТКА ОШИБОК =====

async def error_handler(_update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        error = context.error
        if error and "Flood" in str(error):
            return
        if isinstance(error, (TimedOut, NetworkError)):
            return
    except Exception:
        pass


def signal_handler(signum, _frame):
    global is_running
    print(f"\n📡 Получен сигнал {signum}. Завершение работы...")
    is_running = False


# ===== MAIN =====

async def main():
    global application, word_scheduler, bio_scheduler, is_running

    # Игнорируем SIGTERM от хостинга (чтобы бот не выключался)
    signal.signal(signal.SIGTERM, lambda signum, frame: print("⚠️ Получен SIGTERM от хостинга, игнорирую..."))
    signal.signal(signal.SIGINT, signal_handler)
    is_running = True

    print("🗄 Инициализация базы...")
    init_db()
    os.makedirs(TEMP_DIR, exist_ok=True)

    print("🔌 Подключение к Telegram...")
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            print(f"   Попытка {attempt + 1}/{max_attempts}...")

            application = Application.builder().token(BOT_TOKEN) \
                .connect_timeout(60) \
                .read_timeout(60) \
                .pool_timeout(120) \
                .build()

            application.add_error_handler(error_handler)

            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("words", show_learned_words))
            application.add_handler(CommandHandler("stats", show_stats))
            application.add_handler(CommandHandler("listen", listen_word))
            application.add_handler(CommandHandler("subscribe", subscribe_command))
            application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
            application.add_handler(CommandHandler("users", users_command))
            application.add_handler(CallbackQueryHandler(button_handler))
            application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_answer)
            )

            await application.initialize()
            await application.start()
            
            try:
                await application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True
                )
            except Exception as e:
                if "Conflict" in str(e):
                    print("❌ Бот уже запущен. Остановите другой экземпляр!")
                    await application.stop()
                    return
                raise

            print("✅ Подключено!")
            break

        except (TimedOut, NetworkError):
            print(f"⚠️ Таймаут (попытка {attempt + 1})")
            if attempt < max_attempts - 1:
                wait = (attempt + 1) * 5
                print(f"⏳ Ожидание {wait}с...")
                await asyncio.sleep(wait)
            else:
                print("❌ Не удалось подключиться")
                return
        except Exception as error:
            print(f"❌ Ошибка: {error}")
            return

    word_scheduler = setup_scheduler(application)
    bio_scheduler = setup_bio_update_scheduler(application)

    print("✅ Бот запущен!")
    print("🔄 Система автопереподключения активирована")

    await asyncio.sleep(2)
    await update_bot_bio(application)

    watchdog_task = asyncio.create_task(connection_watchdog(application))

    while is_running:
        await asyncio.sleep(1)

    print("🛑 Завершение работы...")
    watchdog_task.cancel()
    try:
        await application.updater.stop()
        await application.stop()
    except Exception:
        pass
    if word_scheduler:
        word_scheduler.shutdown()
    if bio_scheduler:
        bio_scheduler.shutdown()
    print("👋 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
