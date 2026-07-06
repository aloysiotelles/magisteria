from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    APP_NAME = "MAGISTERIA"
    APP_PASSWORD = os.getenv("APP_PASSWORD", "DIVINA")
    DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(BASE_DIR / "Documentos"))).expanduser()
    VECTOR_DIR = Path(os.getenv("VECTOR_DIR", str(BASE_DIR / "banco_vetorial"))).expanduser()
    INDEX_FILE = VECTOR_DIR / "indice.json"
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano").strip()
    OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip()
    IMAGE_CONCURRENCY = int(os.getenv("IMAGE_CONCURRENCY", "3"))
    IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "low").strip()
    MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "16"))
    MIN_RELEVANCE_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.08"))
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1100"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "180"))


settings = Settings()
settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
settings.VECTOR_DIR.mkdir(parents=True, exist_ok=True)
