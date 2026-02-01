"""Configuration settings for KB Lockup"""

from pydantic_settings import BaseSettings
from pathlib import Path
import warnings

# Suppress BeautifulSoup XML warning
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Keys
    dart_api_key: str = ""
    qwen_api_key: str = ""
    telegram_bot_token: str = ""

    # Database
    db_path: Path = Path("/Users/sol/kb_lockupbot/data/kb_lockup.db")

    # DART settings
    dart_base_url: str = "https://opendart.fss.or.kr/api"
    dart_rate_limit: int = 1000  # requests per day
    dart_timeout: float = 30.0

    # Extraction settings
    qwen_model: str = "qwen-plus"
    qwen_api_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode"
    min_extraction_score: float = 0.6

    @property
    def qwen_base_url_v1(self) -> str:
        """Return base URL with /v1 suffix for OpenAI client compatibility"""
        url = self.qwen_api_base_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        return url

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
