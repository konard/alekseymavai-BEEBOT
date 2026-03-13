import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL")  # Optional proxy URL

# Embeddings
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# Paths
DATA_DIR = BASE_DIR / "data"
PDFS_DIR = DATA_DIR / "pdfs"
SUBTITLES_DIR = DATA_DIR / "subtitles"
TEXTS_DIR = DATA_DIR / "texts"
PROCESSED_DIR = DATA_DIR / "processed"
FAISS_INDEX_PATH = PROCESSED_DIR / "index.faiss"
CHUNKS_PATH = PROCESSED_DIR / "chunks.json"

# Integram CRM
INTEGRAM_URL = os.getenv("INTEGRAM_URL")
INTEGRAM_LOGIN = os.getenv("INTEGRAM_LOGIN")
INTEGRAM_PASSWORD = os.getenv("INTEGRAM_PASSWORD")
INTEGRAM_DB = os.getenv("INTEGRAM_DB")

# Bot settings
MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "5"))
MAX_RESPONSE_LENGTH = int(os.getenv("MAX_RESPONSE_LENGTH", "4096"))
