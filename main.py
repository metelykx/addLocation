import logging
import json
import os
from datetime import datetime
from telegram import Update, InputMediaPhoto, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# Конфигурация
BOT_TOKEN = "7477798413:AAH0hRlFEEWCtrxqwKeHYifaGlhS-j5jCLY"
ADMIN_LOGIN = "putevod-admin"
ADMIN_PASSWORD = "Jingle2018"
ATTRACTIONS_FILE = "attractions.json"
SESSIONS_FILE = "sessions.json"

# Состояния диалога
LOGIN, PASSWORD, NAME, DESCRIPTION, LOCATION, PHOTOS = range(6)

# Хранилища данных
authorized_users = set()
temp_data = {}
attractions = {}
sessions = {}

# Клавиатура для продолжения
continue_keyboard = ReplyKeyboardMarkup(
    [["Продолжить добавление"]],
    resize_keyboard=True,
    one_time_keyboard=True
)


# Инициализация хранилища
def init_storage():
    global attractions, sessions

    # Загрузка достопримечательностей
    if os.path.exists(ATTRACTIONS_FILE):
        try:
            with open(ATTRACTIONS_FILE, 'r', encoding='utf-8') as f:
                attractions = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки attractions.json: {e}")
            attractions = {}
    else:
        attractions = {}

    # Загрузка сессий
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
                # Преобразование ключей в int (JSON сохраняет ключи словарей как строки)
                sessions = {int(k): v for k, v in sessions.items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки sessions.json: {e}")
            sessions = {}
    else:
        sessions = {}

    # Загрузка авторизованных пользователей
    current_time = datetime.now().timestamp()
    for chat_id, expires_at in list(sessions.items()):
        if expires_at > current_time:
            authorized_users.add(chat_id)
        else:
            # Удаляем просроченные сессии
            del sessions[chat_id]

    # Сохранение обновленных сессий
    save_sessions()


# Сохранение достопримечательности
def save_attraction(name, description, latitude, longitude, photos):
    # Проверка на уникальность названия
    if name in attractions:
        return False

    # Создание новой записи
    attractions[name] = {
        "description": description,
        "latitude": latitude,
        "longitude": longitude,
        "photos": photos,
        "created_at": datetime.now().isoformat()
    }

    # Сохранение в файл
    try:
        with open(ATTRACTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(attractions, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения достопримечательности: {e}")
        return False


# Сохранение сессии
def save_session(chat_id):
    # Сессия действительна 30 дней
    sessions[chat_id] = datetime.now().timestamp() + 30 * 24 * 3600
    save_sessions()


# Сохранение всех сессий в файл
def save_sessions():
    try:
        with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения сессий: {e}")


# Проверка авторизации пользователя
def is_authorized(chat_id):
    # Проверка срока действия сессии
    if chat_id in sessions:
        if sessions[chat_id] < datetime.now().timestamp():
            # Сессия истекла
            del sessions[chat_id]
            if chat_id in authorized_users:
                authorized_users.remove(chat_id)
            save_sessions()
            return False
        return True
    return False


# Инициализация хранилища при запуске
init_storage()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id

    if is_authorized(chat_id):
        await update.message.reply_text(
            "🔓 Вы уже авторизованы!\n\n"
            "Введите название новой достопримечательности:",
            reply_markup=ReplyKeyboardRemove()
        )
        return NAME

    await update.message.reply_text(
        "🏛️ Добро пожаловать в систему управления достопримечательностями!\n"
        "Введите ваш логин:",
        reply_markup=ReplyKeyboardRemove()
    )
    return LOGIN


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text
    if user_input == ADMIN_LOGIN:
        temp_data[update.effective_chat.id] = {}
        await update.message.reply_text("✅ Логин верный. Теперь введите пароль:")
        return PASSWORD
    else:
        await update.message.reply_text("❌ Неверный логин. Попробуйте снова:")
        return LOGIN


async def password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    user_input = update.message.text

    if user_input == ADMIN_PASSWORD:
        authorized_users.add(chat_id)
        save_session(chat_id)  # Сохраняем сессию

        await update.message.reply_text(
            "🔓 Авторизация успешна!\n\n"
            "Введите название достопримечательности:",
            reply_markup=ReplyKeyboardRemove()
        )
        return NAME
    else:
        await update.message.reply_text("❌ Неверный пароль. Попробуйте снова:")
        return PASSWORD


async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    temp_data[chat_id] = {"name": update.message.text}
    await update.message.reply_text("📝 Введите описание достопримечательности:")
    return DESCRIPTION


async def description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    temp_data[chat_id]["description"] = update.message.text
    await update.message.reply_text(
        "📍 Введите координаты достопримечательности в формате:\n"
        "<i>широта, долгота</i>\n\n"
        "Пример: <code>55.755826, 37.617300</code>",
        parse_mode="HTML"
    )
    return LOCATION


async def location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    user_input = update.message.text

    try:
        lat, lon = map(str.strip, user_input.split(','))
        lat = float(lat)
        lon = float(lon)

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Неверный диапазон координат")

        temp_data[chat_id]["location"] = (lat, lon)
        await update.message.reply_text(
            "📸 Отправьте 2-3 фотографии достопримечательности (одним сообщением):"
        )
        return PHOTOS

    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Неверный формат координат. Пожалуйста, введите в формате:\n"
            "<i>широта, долгота</i>\n\n"
            "Пример: <code>55.755826, 37.617300</code>",
            parse_mode="HTML"
        )
        return LOCATION


async def photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    photos = update.message.photo

    if not photos:
        await update.message.reply_text("❌ Пожалуйста, отправьте фотографии.")
        return PHOTOS

    file_ids = [photo.file_id for photo in photos[:3]]
    name = temp_data[chat_id]["name"]
    description = temp_data[chat_id]["description"]
    lat, lon = temp_data[chat_id]["location"]

    # Сохраняем в JSON
    success = save_attraction(name, description, lat, lon, file_ids)

    if not success:
        await update.message.reply_text(
            f"❌ Ошибка: Достопримечательность с названием '{name}' уже существует!",
            reply_markup=continue_keyboard
        )
        return ConversationHandler.END

    # Отправляем подтверждение
    media_group = [InputMediaPhoto(file_id) for file_id in file_ids]
    await context.bot.send_media_group(chat_id=chat_id, media=media_group)

    await update.message.reply_text(
        f"✅ Достопримечательность сохранена!\n\n"
        f"<b>Название:</b> {name}\n"
        f"<b>Описание:</b> {description}\n"
        f"<b>Координаты:</b> {lat:.6f}, {lon:.6f}\n\n"
        "Хотите добавить еще одну достопримечательность?",
        parse_mode="HTML",
        reply_markup=continue_keyboard
    )

    if chat_id in temp_data:
        del temp_data[chat_id]

    return ConversationHandler.END


async def continue_adding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if is_authorized(update.effective_chat.id):
        await update.message.reply_text(
            "Введите название новой достопримечательности:",
            reply_markup=ReplyKeyboardRemove()
        )
        return NAME
    else:
        await update.message.reply_text(
            "❌ Вы не авторизованы! Введите /start для авторизации.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if chat_id in temp_data:
        del temp_data[chat_id]
    await update.message.reply_text(
        "❌ Операция отменена.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    # Удаляем из авторизованных
    if chat_id in authorized_users:
        authorized_users.remove(chat_id)

    # Удаляем сессию
    if chat_id in sessions:
        del sessions[chat_id]
        save_sessions()

    if chat_id in temp_data:
        del temp_data[chat_id]

    await update.message.reply_text(
        "🔒 Вы вышли из системы. Для доступа требуется повторная авторизация.",
        reply_markup=ReplyKeyboardRemove()
    )


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex(r'^Продолжить добавление$'), continue_adding)
        ],
        states={
            LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location)],
            PHOTOS: [MessageHandler(filters.PHOTO, photos)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('logout', logout)
        ],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("logout", logout))

    application.add_handler(MessageHandler(
        filters.Regex(r'^Продолжить добавление$'),
        continue_adding
    ))

    application.run_polling()


if __name__ == '__main__':
    main()