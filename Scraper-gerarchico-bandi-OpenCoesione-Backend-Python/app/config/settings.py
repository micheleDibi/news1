from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from decimal import Decimal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Supabase / PostgreSQL ---
    database_url: str = Field(..., description="PostgreSQL connection string (psycopg2 format)")
    database_pooler_host: Optional[str] = Field(
        default=None,
        description="Host del Supabase pooler (IPv4), es. aws-1-eu-central-1.pooler.supabase.com",
    )
    database_pooler_port: int = Field(default=6543, description="Porta del Supabase pooler")
    database_connect_timeout_seconds: int = Field(default=10, description="Timeout connessione DB")
    database_sslmode: str = Field(default="require", description="SSL mode psycopg2")
    database_pool_min: int = Field(default=1, description="Connessioni minime mantenute nel pool client-side")
    database_pool_max: int = Field(default=5, description="Connessioni massime nel pool client-side")
    database_connect_retry_max: int = Field(
        default=4,
        description="Tentativi massimi per acquisire una connessione su errori transitori del pooler Supabase",
    )
    database_connect_retry_base_delay_seconds: float = Field(
        default=0.5,
        description="Ritardo base (secondi) per il backoff esponenziale tra retry di acquisizione",
    )
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_key: str = Field(..., description="Supabase service-role key (anon per lettura pubblica)")

    # --- OpenAI ---
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="Modello OpenAI da usare")

    # --- OCR ---
    tesseract_cmd: str = Field(default="tesseract", description="Percorso eseguibile Tesseract")
    ocr_language: str = Field(default="ita+eng", description="Lingue OCR")

    # --- Scraping ---
    source_root_url: str = Field(
        default="https://opencoesione.gov.it/it/opportunita_2021_2027/",
        description="URL radice OpenCoesione da cui parte lo scraping",
    )
    scraper_concurrency: int = Field(default=5, description="Numero massimo di worker paralleli")
    scraper_timeout_seconds: int = Field(default=30, description="Timeout HTTP singola richiesta")
    scraper_retry_max: int = Field(default=3, description="Tentativi massimi di retry")
    scraper_retry_delay_seconds: int = Field(default=5, description="Attesa tra i retry (secondi)")
    importo_plausibile_threshold: Decimal = Field(
        default=Decimal("1000"),
        description="Soglia usata dal parser per preferire importi plausibili quando ci sono più candidati",
    )

    # --- Redis / Celery ---
    redis_url: str = Field(default="redis://localhost:6379/0", description="URL Redis per Celery")
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/1")

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Livello logging (DEBUG, INFO, WARNING, ERROR)")
    log_json: bool = Field(default=True, description="Output log in formato JSON strutturato")


settings = Settings()
