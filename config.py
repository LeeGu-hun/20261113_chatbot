import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DB_PATH = ROOT / 'data' / 'chatbot.sqlite3'
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
CHAT_MODEL = os.getenv('CHAT_MODEL', 'qwen3.5:4b')
EMBED_MODEL = os.getenv('EMBED_MODEL', 'qwen3-embedding:0.6b')
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '15'))
MAX_DOC_CHUNKS = int(os.getenv('MAX_DOC_CHUNKS', '500'))
TOP_K = max(1, min(10, int(os.getenv('TOP_K', '5'))))
MIN_SIMILARITY = float(os.getenv('MIN_SIMILARITY', '0.30'))
SESSION_SECRET = os.getenv('SESSION_SECRET', '')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
HTTPS_ONLY = os.getenv('SESSION_HTTPS_ONLY', 'false').lower() == 'true'
