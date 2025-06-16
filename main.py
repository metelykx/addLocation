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
from db_config import init_db_pool, check_landmark_exists, save_landmark, save_photo, get_all_landmarks, delete_landmark_by_id, get_landmark_by_id, update_landmark_field
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
PROXY_URL = os.getenv('PROXY_URL')

# Проверка наличия необходимых переменных окружения
if not all([BOT_TOKEN, ADMIN_LOGIN, ADMIN_PASSWORD]):
    logger.error("Missing required environment variables. Please check your .env file.")
    raise ValueError("Missing required environment variables. Please check your .env file.")

# Состояния диалога
(
    LOGIN, PASSWORD,
    NAME, ADDRESS, CATEGORY,
    DESCRIPTION, HISTORY,
    LOCATION, PHOTOS, IMAGE_NAME,
    EDIT_FIELD, EDIT_VALUE
) = range(12)

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

# Клавиатура для выбора поля редактирования
edit_field_keyboard = ReplyKeyboardMarkup(
    [
        ["Название", "Адрес"],
        ["Категория", "Описание"],
        ["История", "Координаты"],
        ["Имя файла фото"]
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

async def edit_landmark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        if not is_authorized(chat_id):
            await update.message.reply_text("❌ Вы не авторизованы! Используйте /start для входа.")
            return ConversationHandler.END

        args = context.args
        if not args or not args[0].isdigit():
            await update.message.reply_text("❌ Используйте команду так: /edit <id>")
            return ConversationHandler.END

        landmark_id = int(args[0])
        landmark = get_landmark_by_id(landmark_id)
        if not landmark:
            await update.message.reply_text(f"❌ Достопримечательность с ID {landmark_id} не найдена.")
            return ConversationHandler.END

        temp_data[chat_id] = {"edit_id": landmark_id}
        await update.message.reply_text(
            f"📝 Редактирование достопримечательности ID {landmark_id}\n"
            f"Текущие данные:\n"
            f"<b>Название:</b> {landmark['name']}\n"
            f"<b>Адрес:</b> {landmark['address']}\n"
            f"<b>Категория:</b> {landmark['category']}\n"
            f"<b>Описание:</b> {landmark['description']}\n"
            f"<b>История:</b> {landmark['history']}\n"
            f"<b>Координаты:</b> {landmark['latitude']:.6f}, {landmark['longitude']:.6f}\n"
            f"<b>Имя файла:</b> {landmark['images_name']}\n\n"
            "Выберите поле для редактирования:",
            parse_mode="HTML",
            reply_markup=edit_field_keyboard
        )
        return EDIT_FIELD
    except Exception as e:
        logger.error(f"Error in edit_landmark handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        field = update.message.text

        field_map = {
            "Название": "name",
            "Адрес": "address",
            "Категория": "category",
            "Описание": "description",
            "История": "history",
            "Координаты": "location",
            "Имя файла фото": "images_name"
        }

        if field not in field_map:
            await update.message.reply_text(
                "❌ Неверное поле. Пожалуйста, выберите поле из предложенных:",
                reply_markup=edit_field_keyboard
            )
            return EDIT_FIELD

        temp_data[chat_id]["edit_field"] = field_map[field]
        
        if field == "Категория":
            await update.message.reply_text(
                "📌 Выберите новую категорию:",
                reply_markup=categories_keyboard
            )
        elif field == "Координаты":
            await update.message.reply_text(
                "📍 Введите новые координаты в формате:\n"
                "<i>широта, долгота</i>\n\n"
                "Пример: <code>44.511777, 34.233452</code>",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove()
            )
        elif field == "Имя файла фото":
            await update.message.reply_text(
                "📸 Отправьте новую фотографию достопримечательности:"
            )
            temp_data[chat_id]["awaiting_photo"] = True
            return EDIT_VALUE
        else:
            await update.message.reply_text(
                f"📝 Введите новое значение для поля '{field}':",
                reply_markup=ReplyKeyboardRemove()
            )

        return EDIT_VALUE
    except Exception as e:
        logger.error(f"Error in edit_field handler: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте снова или обратитесь к администратору."
        )
        return ConversationHandler.END

async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        chat_id = update.effective_chat.id
        landmark_id = temp_data[chat_id]["edit_id"]
        field = temp_data[chat_id]["edit_field"]

        if "awaiting_photo" in temp_data[chat_id] and temp_data[chat_id]["awaiting_photo"]:
            photos = update.message.photo
            if not photos:
                await update.message.reply_text("❌ Пожалуйста, отправьте фотографию.")
                return EDIT_VALUE

            photo = max(photos, key=lambda x: x.file_size)
            temp_data[chat_id]["photo"] = photo.file_id
            await update.message.reply_text(
                "📝 Введите новое имя файла для фотографии (например: landmark_photo.jpg):"
            )
            temp_data[chat_id]["awaiting_photo"] = False
            return EDIT_VALUE

        if field == "images_name":
            images_name = update.message.text
            if not await save_photo(context.bot, temp_data[chat_id]["photo"], images_name):
                await update.message.reply_text(
                    "❌ Ошибка при сохранении фотографии. Попробуйте позже.",
                    reply_markup=continue_keyboard
                )
                return ConversationHandler.END
            success = update_landmark_field(landmark_id, field, images_name)
        elif field == "location":
            try:
                lat, lon = map(str.strip, update.message.text.split(','))
                lat = float(lat)
                lon = float(lon)
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    raise ValueError("Неверный диапазон координат")
                success = update_landmark_field(landmark_id, field, (lat, lon))
            except (ValueError, IndexError):
                await update.message.reply_text(
                    "❌ Неверный формат координат. Пожалуйста, введите в формате:\n"
                    "<i>широта, долгота</i>\n\n"
                    "Пример: <code>44.511777, 34.233452</code>",
                    parse_mode="HTML"
                )
                return EDIT_VALUE
        else:
            success = update_landmark_field(landmark_id, field, update.message.text)

        if success:
            landmark = get_landmark_by_id(landmark_id)
            await update.message.reply_text(
                f"✅ Поле успешно обновлено!\n\n"
                f"<b>Название:</b> {landmark['name']}\n"
                f"<b>Адрес:</b> {landmark['address']}\n"
                f"<b>Категория:</b> {landmark['category']}\n"
                f"<b>Описание:</b> {landmark['description']}\n"
                f"<b>История:</b> {landmark['history']}\n"
                f"<b>Координаты:</b> {landmark['latitude']:.6f}, {landmark['longitude']:.6f}\n"
                f"<b>Имя файла:</b> {landmark['images_name']}\n\n"
                "Хотите добавить еще одну достопримечательность?",
                parse_mode="HTML",
                reply_markup=continue_keyboard
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при обновлении поля. Попробуйте снова.",
                reply_markup=continue_keyboard
            )

        if chat_id in temp_data:
            del temp_data[chat_id]
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in edit_value handler: {e}")
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

def is_authorized(chat_id: int) -> bool:
    return chat_id in authorized_users

# Команда /list для вывода всех достопримечательностей
MAX_ENTRIES_PER_MSG = 20

async def list_landmarks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        landmarks = get_all_landmarks()
        if not landmarks:
            await update.message.reply_text("В базе данных нет достопримечательностей.")
            return

        # Разбиваем список на чанки по 20 записей
        for i in range(0, len(landmarks), MAX_ENTRIES_PER_MSG):
            chunk = landmarks[i:i + MAX_ENTRIES_PER_MSG]
            msg = "📚 Список достопримечательностей:\n\n"
            for lm in chunk:
                msg += (
                    f"ID: {lm[0]}\n"
                    f"Название: {lm[1]}\n"
                    f"Категория: {lm[3]}\n"
                    f"Адрес: {lm[2]}\n\n"
                )
            await update.message.reply_text(msg)

    except Exception as e:
        logger.error(f"Error in list_landmarks handler: {e}")
        await update.message.reply_text("Ошибка при получении списка достопримечательностей.")

# Команда /delete <id> для удаления записи по ID
async def delete_landmark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id = update.effective_chat.id
        if not is_authorized(chat_id):
            await update.message.reply_text("❌ Вы не авторизованы! Используйте /start для входа.")
            return

        args = context.args
        if not args or not args[0].isdigit():
            await update.message.reply_text("❌ Используйте команду так: /delete <id>")
            return

        landmark_id = int(args[0])
        deleted = delete_landmark_by_id(landmark_id)
        if deleted:
            await update.message.reply_text(f"✅ Достопримечательность с ID {landmark_id} удалена.")
        else:
            await update.message.reply_text(f"❌ Достопримечательность с ID {landmark_id} не найдена.")
    except Exception as e:
        logger.error(f"Error in delete_landmark handler: {e}")
        await update.message.reply_text("Ошибка при удалении достопримечательности.")

def main():
    request = HTTPXRequest(proxy_url=PROXY_URL) if PROXY_URL else None
    application = Application.builder().token(BOT_TOKEN).request(request).build()

    # Основной конверсершн хендлер для регистрации/добавления
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('edit', edit_landmark)
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
            IMAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, image_name)],
            EDIT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field)],
            EDIT_VALUE: [
                MessageHandler(filters.PHOTO, edit_value),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel), 
            MessageHandler(filters.Regex('^(Продолжить добавление)$'), continue_adding)
        ]
    )
    application.add_handler(conv_handler)

    # Другие команды
    application.add_handler(CommandHandler("list", list_landmarks))
    application.add_handler(CommandHandler("delete", delete_landmark))
    application.add_handler(CommandHandler("logout", logout))

    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()