from pathlib import Path
from decimal import Decimal, InvalidOperation
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _decimal_env(name: str, default: str = "0") -> Decimal:
    try:
        return Decimal(os.getenv(name, default).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError):
        return Decimal(default).quantize(Decimal("0.01"))


def _public_url() -> str:
    configured = os.getenv("APP_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{railway_domain}" if railway_domain else ""


class Settings:
    APP_NAME = "MAGISTERIA"
    APP_PASSWORD = os.getenv("APP_PASSWORD", "DIVINA")
    DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(BASE_DIR / "Documentos"))).expanduser()
    VECTOR_DIR = Path(os.getenv("VECTOR_DIR", str(BASE_DIR / "banco_vetorial"))).expanduser()
    INDEX_FILE = VECTOR_DIR / "indice.json"
    APP_DATABASE_FILE = Path(os.getenv("APP_DATABASE_FILE", str(VECTOR_DIR / "magisteria.sqlite"))).expanduser()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano").strip()
    OPENAI_REVIEW_MODEL = os.getenv("OPENAI_REVIEW_MODEL", "gpt-5.4-nano").strip()
    OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip()
    IMAGE_CONCURRENCY = int(os.getenv("IMAGE_CONCURRENCY", "3"))
    IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "low").strip()
    MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "16"))
    MIN_RELEVANCE_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.08"))
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1100"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "180"))
    APP_PUBLIC_URL = _public_url()
    ASAAS_API_KEY = os.getenv("ASAAS_API_KEY", "").strip()
    ASAAS_WEBHOOK_TOKEN = os.getenv("ASAAS_WEBHOOK_TOKEN", "").strip()
    ASAAS_API_BASE_URL = os.getenv(
        "ASAAS_API_BASE_URL", "https://api-sandbox.asaas.com/v3"
    ).strip().rstrip("/")
    ASAAS_PRICE = _decimal_env("ASAAS_PRICE", "14.99")
    ASAAS_BILLING_TYPE = os.getenv("ASAAS_BILLING_TYPE", "UNDEFINED").strip().upper()
    MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "").strip()
    MERCADO_PAGO_WEBHOOK_SECRET = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "").strip()
    MERCADO_PAGO_PRICE = _decimal_env("MERCADO_PAGO_PRICE")
    MERCADO_PAGO_CURRENCY = os.getenv("MERCADO_PAGO_CURRENCY", "BRL").strip().upper()


settings = Settings()
settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
settings.VECTOR_DIR.mkdir(parents=True, exist_ok=True)
