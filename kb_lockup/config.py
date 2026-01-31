"""Configuration settings for KB Lockup"""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Keys
    dart_api_key: str = ""
    qwen_api_key: str = ""
    telegram_bot_token: str = ""

    # Database
    db_path: Path = Path("data/kb_lockup.db")

    # DART settings
    dart_base_url: str = "https://opendart.fss.or.kr/api"
    dart_rate_limit: int = 1000  # requests per day
    dart_timeout: float = 30.0

    # Extraction settings
    qwen_model: str = "qwen-plus"
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_api_base_url: str = ""  # Alternative env var name
    min_extraction_score: float = 0.6

    def get_qwen_base_url(self) -> str:
        """Get Qwen base URL, checking alternative env var"""
        if self.qwen_api_base_url:
            url = self.qwen_api_base_url
            # Ensure /v1 suffix
            if not url.endswith("/v1"):
                url = url.rstrip("/") + "/v1"
            return url
        return self.qwen_base_url

    # Telegram settings
    reminder_check_hour: int = 8
    reminder_timezone: str = "Asia/Seoul"

    # Paths
    data_dir: Path = Path("data")
    export_dir: Path = Path("exports")
    cache_dir: Path = Path("data/cache")

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
