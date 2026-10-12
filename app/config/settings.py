"""
DMS Analytics - Application Settings
"""
import os
from pathlib import Path

# Load .env if present
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        # Fallback simple .env reader if python-dotenv is not installed
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


class Settings:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # Environment
    APP_ENV: str = os.environ.get("APP_ENV", "production").lower()

    # Cryptography & Security
    DMS_AES_KEY_HEX: str = os.environ.get("DMS_AES_KEY_HEX", "")
    DMS_RSA_PASSPHRASE: str = os.environ.get("DMS_RSA_PASSPHRASE", "")
    DMS_RSA_PRIVATE_KEY_PEM: str = os.environ.get("DMS_RSA_PRIVATE_KEY_PEM", "")

    # Default DB User / Credentials
    DMS_DB_USER: str = os.environ.get("DMS_DB_USER", "postgres")
    DMS_DB_PASSWORD: str = os.environ.get("DMS_DB_PASSWORD", "postgres")

    # LLM Provider Configuration ("oci" for OCI Generative AI, "google" for Direct Google Gemini API)
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "oci").lower()

    # Service 1: OCI Generative AI (Google Gemini 2.5 Flash — Hyderabad Region ap-hyderabad-1)
    OCI_BASE_URL: str = os.environ.get("OCI_BASE_URL", "https://inference.generativeai.ap-hyderabad-1.oci.oraclecloud.com/openai/v1")
    OCI_MODEL: str = os.environ.get("OCI_MODEL", "google.gemini-2.5-flash")
    OCI_API_KEY: str = os.environ.get("OCI_API_KEY", "")
    OCI_PROJECT_OCID: str = os.environ.get("OCI_PROJECT_OCID", "ocid1.generativeaiproject.oc1.ap-hyderabad-1.amaaaaaalvtqzhaad5m2tenvirzcv25yjlosg2xteh43fshcxv5zircmucya")
    OCI_COMPARTMENT_ID: str = os.environ.get("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..aaaaaaaak4o77iye33a7yrcr4zhume57an74tkwluwae4n32bzmqihekatba")
    OCI_REGION: str = os.environ.get("OCI_REGION", "ap-hyderabad-1")

    # Service 2: Native Google Gemini API Service
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
    LLM_CACHE_TTL: int = int(os.environ.get("LLM_CACHE_TTL", "300"))

    # Google Speech-to-Text / Cloud
    GOOGLE_APPLICATION_CREDENTIALS: str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    # DB
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

    # Server
    HOST: str = os.environ.get("HOST", "127.0.0.1")
    PORT: int = int(os.environ.get("PORT", "13000"))

    # Static
    STATIC_DIR: Path = Path(__file__).resolve().parent.parent / "static"

    def has_gemini_key(self) -> bool:
        return bool((self.GEMINI_API_KEY or "").strip())


settings = Settings()
