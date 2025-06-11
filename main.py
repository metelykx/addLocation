import logging
import os
import sys
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
from telegram.error import NetworkError, TimedOut, TelegramError
from db_config import init_db_pool, check_landmark_exists, save_landmark, save_photo
from dotenv import load_dotenv
import asyncio
import traceback
import httpx
from telegram.request import HTTPXRequest

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_LOGIN = os.getenv('ADMIN_LOGIN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
PROXY_URL = os.getenv('PROXY_URL')  # Добавляем поддержку прокси

# Проверка наличия необходимых переменных окружения
if not all([BOT_TOKEN, ADMIN_LOGIN, ADMIN_PASSWORD]):
    logger.error("Missing required environment variables. Please check your .env file.")
    raise ValueError("Missing required environment variables. Please check your .env file.")

# Состояния диалога
(
    LOGIN, PASSWORD,
    NAME, ADDRESS, CATEGORY,
    DESCRIPTION, HISTORY,
    LOCATION, PHOTOS, IMAGE_NAME
) = range(10)

# Хранилища данных
authorized_users = set()
temp_data = {}

# Клавиатура для продолжения
continue_keyboard = ReplyKeyboardMarkup(
    [["Продолжить добавление"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Категории для клавиатуры
categories_keyboard = ReplyKeyboardMarkup(
    [
        ["Замки", "Религия"],
        ["Музей", "Архитектура"],
        ["Памятник", "Парк"],
        ["Природа", "Театр"],
        ["Концертный зал", "Необычное"],
        ["Археология", "Арт-объект"],
        ["Фонтан", "Наука"]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the telegram bot."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(context.error, NetworkError):
        logger.error("Network error occurred. Will retry automatically.")
    elif isinstance(context.error, TimedOut):
        logger.error("Request timed out. Will retry automatically.")
    else:
        logger.error(f"Update {update} caused error {context.error}")
        logger.error(traceback.format_exc())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id

        if is_authorized(chat_id):
            await update.message.reply_text(
                "🔓 Вы уже авторизованы!\n\n"
                "Введите название достопримечательности:",
                reply_markup=ReplyKeyboardRemove()
            )
            return NAME

        await update.message.reply_text(
            "🏛️ Добро пожаловать в систему управления достопримечательностями!\n"
            "Введите ваш логин:",
            reply_markup=ReplyKeyboardRemove()
        )
        return LOGIN
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_input = update.message.text
        if user_input == ADMIN_LOGIN:
            temp_data[update.effective_chat.id] = {}
            await update.message.reply_text("✅ Логин верный. Теперь введите пароль:")
            return PASSWORD
        else:
            await update.message.reply_text("❌ Неверный логин. Попробуйте снова:")
            return LOGIN
    except Exception as e:
        logger.error(f"Error in login handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        user_input = update.message.text

        if user_input == ADMIN_PASSWORD:
            authorized_users.add(chat_id)
            await update.message.reply_text(
                "🔓 Авторизация успешна!\n\n"
                "Введите название достопримечательности:",
                reply_markup=ReplyKeyboardRemove()
            )
            return NAME
        else:
            await update.message.reply_text("❌ Неверный пароль. Попробуйте снова:")
            return PASSWORD
    except Exception as e:
        logger.error(f"Error in password handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        name = update.message.text

        if check_landmark_exists(name):
            await update.message.reply_text(
                f"❌ Достопримечательность с названием '{name}' уже существует в базе данных.",
                reply_markup=continue_keyboard
            )
            return ConversationHandler.END

        temp_data[chat_id] = {"name": name}
        await update.message.reply_text("🏠 Введите адрес достопримечательности:")
        return ADDRESS
    except Exception as e:
        logger.error(f"Error in name handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        temp_data[chat_id]["address"] = update.message.text
        await update.message.reply_text(
            "📌 Выберите категорию достопримечательности:",
            reply_markup=categories_keyboard
        )
        return CATEGORY
    except Exception as e:
        logger.error(f"Error in address handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        temp_data[chat_id]["category"] = update.message.text
        await update.message.reply_text(
            "📝 Введите описание достопримечательности:",
            reply_markup=ReplyKeyboardRemove()
        )
        return DESCRIPTION
    except Exception as e:
        logger.error(f"Error in category handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        temp_data[chat_id]["description"] = update.message.text
        await update.message.reply_text("📜 Введите историческую справку:")
        return HISTORY
    except Exception as e:
        logger.error(f"Error in description handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        temp_data[chat_id]["history"] = update.message.text
        await update.message.reply_text(
            "📍 Введите координаты достопримечательности в формате:\n"
            "<i>широта, долгота</i>\n\n"
            "Пример: <code>44.511777, 34.233452</code>",
            parse_mode="HTML"
        )
        return LOCATION
    except Exception as e:
        logger.error(f"Error in history handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
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
                "📸 Отправьте фотографию достопримечательности:"
            )
            return PHOTOS

        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Неверный формат координат. Пожалуйста, введите в формате:\n"
                "<i>широта, долгота</i>\n\n"
                "Пример: <code>44.511777, 34.233452</code>",
                parse_mode="HTML"
            )
            return LOCATION
    except Exception as e:
        logger.error(f"Error in location handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        photos = update.message.photo

        if not photos:
            await update.message.reply_text("❌ Пожалуйста, отправьте фотографию.")
            return PHOTOS

        # Get the highest quality photo
        photo = max(photos, key=lambda x: x.file_size)
        temp_data[chat_id]["photo"] = photo.file_id

        await update.message.reply_text(
            "📝 Введите имя файла для сохранения фотографии (например: landmark_photo.jpg):"
        )
        return IMAGE_NAME
    except Exception as e:
        logger.error(f"Error in photos handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def image_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        images_name = update.message.text

        # Получаем все собранные данные
        data = temp_data[chat_id]
        name = data["name"]
        address = data["address"]
        category = data["category"]
        description = data["description"]
        history = data["history"]
        lat, lon = data["location"]
        photo_file_id = data["photo"]

        # Сохраняем фотографию
        if not await save_photo(context.bot, photo_file_id, images_name):
            await update.message.reply_text(
                "❌ Ошибка при сохранении фотографии. Попробуйте позже.",
                reply_markup=continue_keyboard
            )
            return ConversationHandler.END

        # Сохраняем в базу данных
        success = save_landmark(
            name=name,
            address=address,
            category=category,
            description=description,
            history=history,
            latitude=lat,
            longitude=lon,
            images_name=images_name
        )

        if not success:
            await update.message.reply_text(
                f"❌ Ошибка: Достопримечательность с названием '{name}' уже существует!",
                reply_markup=continue_keyboard
            )
            return ConversationHandler.END

        # Отправляем подтверждение
        await context.bot.send_photo(chat_id=chat_id, photo=photo_file_id)

        await update.message.reply_text(
            f"✅ Достопримечательность сохранена!\n\n"
            f"<b>Название:</b> {name}\n"
            f"<b>Адрес:</b> {address}\n"
            f"<b>Категория:</b> {category}\n"
            f"<b>Описание:</b> {description}\n"
            f"<b>История:</b> {history}\n"
            f"<b>Координаты:</b> {lat:.6f}, {lon:.6f}\n"
            f"<b>Имя файла:</b> {images_name}\n\n"
            "Хотите добавить еще одну достопримечательность?",
            parse_mode="HTML",
            reply_markup=continue_keyboard
        )

        if chat_id in temp_data:
            del temp_data[chat_id]

        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in image_name handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def continue_adding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if is_authorized(update.effective_chat.id):
            await update.message.reply_text(
                "Введите название достопримечательности:",
                reply_markup=ReplyKeyboardRemove()
            )
            return NAME
        else:
            await update.message.reply_text(
                "❌ Вы не авторизованы! Введите /start для авторизации.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in continue_adding handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        if chat_id in temp_data:
            del temp_data[chat_id]
        await update.message.reply_text(
            "❌ Операция отменена.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = update.effective_chat.id
        if chat_id in authorized_users:
            authorized_users.remove(chat_id)
        if chat_id in temp_data:
            del temp_data[chat_id]
        await update.message.reply_text(
            "🔒 Вы вышли из системы. Для доступа требуется повторная авторизация.",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error in logout handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )

def is_authorized(chat_id):
    return chat_id in authorized_users

def main() -> None:
    try:
        # Инициализация базы данных
        init_db_pool()
        logging.info("Database connection initialized successfully")

        # Настройка прокси, если он указан
        if PROXY_URL:
            logger.info(f"Using proxy: {PROXY_URL}")
            request = HTTPXRequest(
                connection_pool_size=8,
                proxy_url=PROXY_URL,
                read_timeout=30.0,
                write_timeout=30.0,
                connect_timeout=30.0,
                pool_timeout=30.0
            )
        else:
            logger.info("No proxy configured, using direct connection")
            request = HTTPXRequest(
                connection_pool_size=8,
                read_timeout=30.0,
                write_timeout=30.0,
                connect_timeout=30.0,
                pool_timeout=30.0
            )

        # Создание приложения с настройками таймаутов и прокси
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .request(request)
            .build()
        )

        # Добавление обработчика ошибок
        application.add_error_handler(error_handler)

        # Настройка обработчиков команд
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('start', start),
                MessageHandler(filters.Regex(r'^Продолжить добавление$'), continue_adding)
            ],
            states={
                LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password)],
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
                ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, address)],
                CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category)],
                DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description)],
                HISTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, history)],
                LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, location)],
                PHOTOS: [MessageHandler(filters.PHOTO, photos)],
                IMAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, image_name)]
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

        # Запуск бота с увеличенным количеством попыток подключения
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            bootstrap_retries=5  # Увеличиваем количество попыток подключения
        )
    except Exception as e:
        logger.error(f"Error running bot: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()