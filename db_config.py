import psycopg2
from psycopg2 import pool
import logging
from typing import Optional, List, Tuple
from datetime import datetime
import os
import shutil
from telegram import Bot, Update
from dotenv import load_dotenv
from telegram.ext import ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем путь к директории текущего файла
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')

# Загрузка переменных окружения
logger.info(f"Loading .env file from: {env_path}")
load_dotenv(env_path)

# Проверка загрузки переменных окружения
logger.info("Checking environment variables...")
for var in ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT']:
    value = os.getenv(var)
    logger.info(f"{var}: {'Set' if value else 'Not set'}")

# Database configuration from environment variables
DB_CONFIG = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'db'),  # Используем 'db' как значение по умолчанию
    'port': os.getenv('DB_PORT', '5432'),
    'client_encoding': 'utf8'
}

# Проверка наличия всех необходимых переменных окружения для БД
required_db_vars = ['DB_NAME', 'DB_USER', 'DB_PASSWORD']
missing_vars = [var for var in required_db_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required database environment variables: {', '.join(missing_vars)}")
    raise ValueError(f"Missing required database environment variables: {', '.join(missing_vars)}")

# Connection pool
connection_pool = None

# Получаем путь к директории для изображений из .env
IMAGES_DIR = os.getenv('IMAGES_DIR', 'images') 

# Создаем директорию, если она не существует
if not os.path.exists(IMAGES_DIR):
    try:
        os.makedirs(IMAGES_DIR)
        logger.info(f"Created images directory at: {IMAGES_DIR}")
    except Exception as e:
        logger.error(f"Failed to create images directory: {e}")
        raise
else:
    logger.info(f"Images directory exists: {IMAGES_DIR}")

def init_db_pool():
    """Initialize the database connection pool"""
    global connection_pool
    try:
        logger.info(f"Initializing database connection pool with config: {DB_CONFIG}")
        connection_pool = pool.SimpleConnectionPool(
            1,  # minconn
            10,  # maxconn
            **DB_CONFIG
        )
        logger.info("Database connection pool initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database connection pool: {e}")
        raise

def get_connection():
    """Get a connection from the pool"""
    if connection_pool is None:
        init_db_pool()
    return connection_pool.getconn()

def release_connection(conn):
    """Release a connection back to the pool"""
    connection_pool.putconn(conn)

def check_landmark_exists(name: str) -> bool:
    """Check if a landmark with the given name exists in the landmark table"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM landmark WHERE name = %s)", (name,))
            exists = cur.fetchone()[0]
            logger.info(f"Checked landmark existence for name '{name}': {exists}")
            return exists
    except Exception as e:
        logger.error(f"Error checking landmark existence for name '{name}': {e}")
        raise
    finally:
        release_connection(conn)

async def save_photo(bot: Bot, file_id: str, images_name: str) -> bool:
    """Save photo to images directory"""
    try:
        # Get file from Telegram
        file = await bot.get_file(file_id)
        
        # Download file
        file_path = os.path.join(IMAGES_DIR, images_name)
        await file.download_to_drive(file_path)
        logger.info(f"Saved photo to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving photo {images_name}: {e}")
        return False

def sync_landmark_sequence():
    """Synchronize the landmark_id_seq with the current max ID in the landmark table"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Create sequence if it doesn't exist
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE sequencename = 'landmark_id_seq') THEN
                        CREATE SEQUENCE landmark_id_seq;
                    END IF;
                END $$;
            """)
            
            # Get current max ID and set sequence value
            cur.execute("""
                SELECT setval('landmark_id_seq', COALESCE((SELECT MAX(id) FROM landmark), 0));
            """)
            conn.commit()
            logger.info("Landmark sequence synchronized")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error syncing landmark sequence: {e}")
    finally:
        release_connection(conn)

def save_landmark(name: str, address: str, category: str, description: str, 
                 history: str, latitude: float, longitude: float, images_name: str) -> bool:
    """Save a new landmark to the database if it doesn't exist"""
    # First check if landmark exists
    if check_landmark_exists(name):
        logger.warning(f"Landmark with name '{name}' already exists")
        return False

    # Sync sequence before inserting
    sync_landmark_sequence()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Insert landmark with photo set to NULL using the sequence
            cur.execute("""
                INSERT INTO landmark (id, name, address, category, description, history, location, images_name, photo)
                VALUES (nextval('landmark_id_seq'), %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, NULL)
                RETURNING id
            """, (name, address, category, description, history, longitude, latitude, images_name))
            
            landmark_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Saved new landmark ID {landmark_id}: {name}")
            return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving landmark '{name}': {e}")
        return False
    finally:
        release_connection(conn)

def get_all_landmarks() -> List[Tuple]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, address, category, description, history,
                       ST_X(location::geometry) as longitude,
                       ST_Y(location::geometry) as latitude,
                       images_name
                FROM landmark
                ORDER BY id
            """)
            landmarks = cur.fetchall()
            logger.info(f"Retrieved {len(landmarks)} landmarks")
            return landmarks
    except Exception as e:
        logger.error(f"Error retrieving landmarks: {e}")
        raise
    finally:
        release_connection(conn)

def get_landmark_by_id(landmark_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, address, category, description, history,
                       ST_X(location::geometry) as longitude,
                       ST_Y(location::geometry) as latitude,
                       images_name
                FROM landmark
                WHERE id = %s
            """, (landmark_id,))
            row = cur.fetchone()
            if row:
                landmark = {
                    'id': row[0],
                    'name': row[1],
                    'address': row[2],
                    'category': row[3],
                    'description': row[4],
                    'history': row[5],
                    'longitude': row[6],
                    'latitude': row[7],
                    'images_name': row[8],
                }
                logger.info(f"Retrieved landmark ID {landmark_id}: {landmark['name']}")
                return landmark
            logger.warning(f"Landmark ID {landmark_id} not found")
            return None
    except Exception as e:
        logger.error(f"Error retrieving landmark ID {landmark_id}: {e}")
        raise
    finally:
        release_connection(conn)

def delete_landmark_by_id(landmark_id: int) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM landmark WHERE id = %s", (landmark_id,))
            conn.commit()
            deleted = cur.rowcount > 0
            logger.info(f"Landmark ID {landmark_id} deletion: {'successful' if deleted else 'not found'}")
            return deleted
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting landmark id={landmark_id}: {e}")
        return False
    finally:
        release_connection(conn)

def update_landmark_field(landmark_id: int, field: str, value: any) -> bool:
    """Update a specific field of a landmark by ID"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if field == "location":
                latitude, longitude = value
                cur.execute("""
                    UPDATE landmark 
                    SET location = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                    WHERE id = %s
                """, (longitude, latitude, landmark_id))
            elif field == "name" and check_landmark_exists(value):
                logger.warning(f"Landmark with name '{value}' already exists")
                return False
            else:
                cur.execute(f"""
                    UPDATE landmark 
                    SET {field} = %s
                    WHERE id = %s
                """, (value, landmark_id))
            
            conn.commit()
            updated = cur.rowcount > 0
            logger.info(f"Updated field {field} for landmark ID {landmark_id}: {'successful' if updated else 'not found'}")
            return updated
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating landmark id={landmark_id}, field={field}: {e}")
        return False
    finally:
        release_connection(conn)

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        landmarks = get_all_landmarks()
        if not landmarks:
            await update.message.reply_text("Нет записей в таблице landmark.")
            return
        text = "Список достопримечательностей:\n"
        for lm in landmarks:
            text += f"ID: {lm[0]}, Название: {lm[1]}, Адрес: {lm[2]}, Категория: {lm[3]}\n"
        await update.message.reply_text(text)
        logger.info(f"Listed landmarks for chat_id {update.effective_chat.id}")
    except Exception as e:
        logger.error(f"Error in list_command: {e}")
        await update.message.reply_text("Ошибка при получении списка достопримечательностей.")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) != 1 or not context.args[0].isdigit():
            await update.message.reply_text("Использование: /delete <id>")
            return
        landmark_id = int(context.args[0])
        success = delete_landmark_by_id(landmark_id)
        if success:
            await update.message.reply_text(f"Запись с ID {landmark_id} удалена.")
            logger.info(f"Landmark ID {landmark_id} deleted")
        else:
            await update.message.reply_text(f"Запись с ID {landmark_id} не найдена или не удалена.")
            logger.warning(f"Landmark ID {landmark_id} not found for deletion")
    except Exception as e:
        logger.error(f"Error in delete_command: {e}")
        await update.message.reply_text("Ошибка при удалении достопримечательности.")

def get_landmark_by_name(name: str) -> Optional[dict]:
    """Get landmark details by name"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT l.*, 
                       ST_X(l.location::geometry) as longitude,
                       ST_Y(l.location::geometry) as latitude,
                       c.category_name
                FROM landmark l
                LEFT JOIN category c ON l.id = c.landmark_id
                WHERE l.name = %s
            """, (name,))
            result = cur.fetchone()
            if result:
                landmark = {
                    'id': result[0],
                    'name': result[1],
                    'address': result[2],
                    'category': result[3],
                    'description': result[4],
                    'history': result[5],
                    'photo': result[6],
                    'location': result[7],  # This is the geography point
                    'latitude': result[8],  # Extracted from location
                    'longitude': result[9],  # Extracted from location
                    'category_name': result[10]
                }
                logger.info(f"Retrieved landmark by name '{name}': ID {landmark['id']}")
                return landmark
            logger.warning(f"Landmark with name '{name}' not found")
            return None
    except Exception as e:
        logger.error(f"Error retrieving landmark by name '{name}': {e}")
        raise
    finally:
        release_connection(conn)