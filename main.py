import asyncio
import sqlite3
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton,
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Инициализация бота с вашим токеном
bot = Bot(
    token="8058786269:AAFbIQvaaP_7IE0kvhq93Es8KNdZ0-1bxgQ",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# База данных
conn = sqlite3.connect('gifts.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    partner_id INTEGER
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    description TEXT,
    link TEXT,
    photo_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)''')
conn.commit()

# Клавиатуры
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Мой список"), KeyboardButton(text="👀 Список любимки")],
            [KeyboardButton(text="➕ Добавить подарок"), KeyboardButton(text="❌ Удалить подарок")]
        ],
        resize_keyboard=True
    )

# Состояния FSM
class AddGift(StatesGroup):
    name = State()
    description = State()
    link = State()
    photo = State()

class AddPartner(StatesGroup):
    waiting = State()

# ===== ОСНОВНЫЕ КОМАНДЫ =====
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        await message.answer("👋 Привет! Как тебя зовут?")
    else:
        await message.answer("Главное меню:", reply_markup=main_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
<b>Доступные команды:</b>
/start - Начать работу
/help - Помощь
/connect - Добавить любимку

<b>Основные кнопки:</b>
🎁 Мой список - Ваши подарки
👀 Список любимки - Подарки вашей любимки
➕ Добавить подарок - Новый подарок
❌ Удалить подарок - Удаление
"""
    await message.answer(help_text)

# ===== РЕГИСТРАЦИЯ =====
@dp.message(lambda message: not is_user_registered(message.from_user.id))
async def register_user(message: types.Message):
    user_id = message.from_user.id
    name = message.text
    
    cursor.execute("INSERT INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    
    await message.answer(f"✅ Отлично, {name}! Теперь добавьте свою любимку через /connect")
    await message.answer("Главное меню:", reply_markup=main_keyboard())

# ===== СИСТЕМА ПАРТНЕРОВ =====
@dp.message(Command("connect"))
async def connect_partner(message: types.Message, state: FSMContext):
    await state.set_state(AddPartner.waiting)
    await message.answer("🔑 Попросите вашу любимку отправить команду /connect")

@dp.message(Command("connect"), AddPartner.waiting)
async def confirm_partner(message: types.Message, state: FSMContext):
    user1_id = message.from_user.id
    cursor.execute("SELECT user_id FROM users WHERE partner_id IS NULL AND user_id != ?", (user1_id,))
    partner = cursor.fetchone()
    
    if partner:
        user2_id = partner[0]
        cursor.execute("UPDATE users SET partner_id = ? WHERE user_id = ?", (user2_id, user1_id))
        cursor.execute("UPDATE users SET partner_id = ? WHERE user_id = ?", (user1_id, user2_id))
        conn.commit()
        
        await message.answer("✅ Ваша любимка успешно добавлена!")
        try:
            await bot.send_message(user2_id, "✅ Вы успешно связаны со своим партнером!")
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")
        
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_keyboard())
    else:
        await message.answer("❌ Нет доступных пользователей для связи")

# ===== РАБОТА С ПОДАРКАМИ =====
@dp.message(F.text == "➕ Добавить подарок")
async def add_gift_start(message: types.Message, state: FSMContext):
    await state.set_state(AddGift.name)
    await message.answer("📝 Введите название подарка:")

@dp.message(AddGift.name)
async def add_gift_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddGift.description)
    await message.answer("💬 Добавьте описание (или /skip):")

@dp.message(AddGift.description)
async def add_gift_desc(message: types.Message, state: FSMContext):
    if message.text != "/skip":
        await state.update_data(description=message.text)
    await state.set_state(AddGift.link)
    await message.answer("🔗 Добавьте ссылку (или /skip):")

@dp.message(AddGift.link)
async def add_gift_link(message: types.Message, state: FSMContext):
    if message.text != "/skip":
        await state.update_data(link=message.text)
    await state.set_state(AddGift.photo)
    await message.answer("📸 Отправьте фото подарка (или /skip):")

@dp.message(AddGift.photo, F.text == "/skip")
async def add_gift_no_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=None)
    await save_gift(message, state)

@dp.message(AddGift.photo, F.photo)
async def add_gift_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await save_gift(message, state)

@dp.message(AddGift.photo)
async def handle_invalid_photo_input(message: types.Message):
    await message.answer("Пожалуйста, отправьте фото подарка или введите /skip")

async def save_gift(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute('''
    INSERT INTO gifts (user_id, name, description, link, photo_id)
    VALUES (?, ?, ?, ?, ?)
    ''', (message.from_user.id, data['name'], data.get('description'), data.get('link'), data.get('photo_id')))
    conn.commit()
    
    partner_id = get_partner_id(message.from_user.id)
    if partner_id:
        try:
            await bot.send_message(
                partner_id,
                f"🎁 Ваш партнер добавил новый подарок: <b>{data['name']}</b>"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")
    
    await state.clear()
    await message.answer("✅ Подарок добавлен!", reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Мой список")
async def show_my_gifts(message: types.Message):
    gifts = get_gifts(message.from_user.id)
    if not gifts:
        await message.answer("Ваш список подарков пуст.")
        return
    
    for gift in gifts:
        gift_id, name, desc, link, photo_id = gift
        text = f"🎁 <b>{name}</b> (ID: {gift_id})\n"
        if desc:
            text += f"📝 {desc}\n"
        if link:
            text += f"🔗 <a href='{link}'>Ссылка</a>\n"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{gift_id}")],
            [InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{gift_id}")]
        ])
        
        if photo_id:
            await message.answer_photo(
                photo_id,
                caption=text,
                reply_markup=kb
            )
        else:
            await message.answer(
                text,
                reply_markup=kb
            )

@dp.message(F.text == "👀 Список любимки")
async def show_partner_gifts(message: types.Message):
    partner_id = get_partner_id(message.from_user.id)
    if not partner_id:
        await message.answer("❌ У вас пока нет любимки в системе")
        return
    
    gifts = get_gifts(partner_id)
    if not gifts:
        await message.answer("Список подарков вашей любимки пока пуст")
        return
    
    for gift in gifts:
        gift_id, name, desc, link, photo_id = gift
        text = f"🎁 <b>{name}</b>\n"
        if desc:
            text += f"📝 {desc}\n"
        if link:
            text += f"🔗 <a href='{link}'>Ссылка</a>\n"
        
        if photo_id:
            await message.answer_photo(
                photo_id,
                caption=text
            )
        else:
            await message.answer(text)

@dp.callback_query(F.data.startswith("delete_"))
async def delete_gift(call: types.CallbackQuery):
    gift_id = call.data.split("_")[1]
    cursor.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
    conn.commit()
    await call.message.delete()
    await call.message.answer("✅ Подарок удален!", reply_markup=main_keyboard())

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_user_registered(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

def get_partner_id(user_id):
    cursor.execute("SELECT partner_id FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None

def get_gifts(user_id):
    cursor.execute("SELECT id, name, description, link, photo_id FROM gifts WHERE user_id = ?", (user_id,))
    return cursor.fetchall()

# ===== ЗАПУСК БОТА С ЗАЩИТОЙ ОТ КОНФЛИКТОВ =====
async def on_startup():
    # Закрываем все предыдущие соединения
    session = await bot.get_session()
    await session.close()
    
    # Удаляем вебхук и старые обновления
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот успешно запущен")

async def on_shutdown():
    await (await bot.get_session()).close()
    conn.close()
    logger.info("Бот остановлен")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        # Добавляем задержку перед стартом
        await asyncio.sleep(5)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await on_shutdown()

if __name__ == "__main__":
    # Для Replit - добавляем keep_alive
    from flask import Flask
    from threading import Thread

    app = Flask(__name__)

    @app.route('/')
    def home(): return "Bot is alive!"

    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    
    # Запускаем бота
    asyncio.run(main())
