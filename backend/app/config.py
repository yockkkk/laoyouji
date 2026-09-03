"""全局配置：pydantic-settings 读取 .env。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 大模型
    llm_provider: str = "mock"  # deepseek | mock
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 语音识别（腾讯一句话识别 | 讯飞语音听写 | mock）
    asr_provider: str = "mock"  # tencent | iflytek | mock
    iflytek_app_id: str = ""
    iflytek_api_key: str = ""
    iflytek_api_secret: str = ""
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    tencent_region: str = "ap-guangzhou"

    # 存储
    storage_backend: str = "local"  # supabase | local
    supabase_url: str = ""
    supabase_service_key: str = ""
    local_data_dir: str = str(BASE_DIR / "local_data")

    # 安全管控
    risk_amount_threshold: float = 50.0
    confirm_timeout_min: int = 30

    # 智能体预算（三级止损：步数在 Agent 类上，token / 墙钟在这儿）
    budget_max_tokens: int = 60_000
    budget_wall_clock_s: float = 90.0
    tool_timeout_s: float = 20.0
    tool_concurrency: int = 4


settings = Settings()
