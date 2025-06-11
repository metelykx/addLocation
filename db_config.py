import psycopg2
from psycopg2 import pool
import logging
from typing import Optional, List, Tuple
from datetime import datetime
import os
import shutil
from telegram import Bot
from dotenv import load_dotenv

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

# Create images directory if it doesn't exist
IMAGES_DIR = "images"
if not os.path.exists(IMAGES_DIR):
    os.makedirs(IMAGES_DIR)

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
        logging.info("Database connection pool initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing database connection pool: {e}")
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
            return cur.fetchone()[0]
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
        return True
    except Exception as e:
        logging.error(f"Error saving photo: {e}")
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
    except Exception as e:
        conn.rollback()
        logging.error(f"Error syncing landmark sequence: {e}")
    finally:
        release_connection(conn)

def save_landmark(name: str, address: str, category: str, description: str, 
                 history: str, latitude: float, longitude: float, images_name: str) -> bool:
    """Save a new landmark to the database if it doesn't exist"""
    # First check if landmark exists
    if check_landmark_exists(name):
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
            return True
    except Exception as e:
        conn.rollback()
        logging.error(f"Error saving landmark: {e}")
        return False
    finally:
        release_connection(conn)

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
                return {
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
            return None
    finally:
        release_connection(conn) 