"""
Application configuration management using Pydantic Settings.

Reads configuration from environment variables and .env files with
type validation and fallback defaults.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration settings."""

    # Project directories
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data" / "raw"
    DEMO_DATA_PATH: Path = DATA_DIR / "transactions_10k.csv"
    DEMO_INFERENCE_DATA_PATH: Path = DATA_DIR / "demo_inference_10.csv"
    ARTIFACTS_DIR: Path = PROJECT_ROOT / "artifacts"
    MODEL_PATH: Path = ARTIFACTS_DIR / "fraud_model.joblib"

    # Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = True

    # PostgreSQL Configuration
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"
    POSTGRES_DB: str = "fraud_detection"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    @property
    def postgres_dsn(self) -> str:
        """Construct PostgreSQL async connection DSN."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_ALERTS_CHANNEL: str = "channel:fraud-alerts"

    # Kafka Configuration
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_TRANSACTIONS: str = "transactions"
    KAFKA_TOPIC_DLQ: str = "transactions-dlq"
    KAFKA_CONSUMER_GROUP: str = "fraud-inference-engine"

    # Model Inference & Decision Thresholds
    FRAUD_THRESHOLD_LOW: float = 0.40
    FRAUD_THRESHOLD_HIGH: float = 0.75
    ANOMALY_THRESHOLD: float = 0.65

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
