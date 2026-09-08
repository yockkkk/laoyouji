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
    tencent_region: str = "ap-shanghai"

    # 存储：local（JSON 文件）| mariadb（服务器直连/SSH 隧道）| supabase（已弃用）| ssh（SFTP JSON）
    storage_backend: str = "local"
    supabase_url: str = ""
    supabase_service_key: str = ""
    local_data_dir: str = str(BASE_DIR / "local_data")

    # STORAGE_BACKEND=ssh：把 JSON 直接存在服务器上（SFTP），给没装数据库的机器兜底
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_password: str = ""
    ssh_data_dir: str = "/tmp/laoyouji_data"

    # STORAGE_BACKEND=mariadb
    mariadb_host: str = ""
    mariadb_port: int = 3306
    mariadb_user: str = ""
    mariadb_password: str = ""
    mariadb_db: str = ""
    # MariaDB 默认 bind-address=127.0.0.1，公网连不上；开这个开关就先拉一条 SSH
    # 隧道再连本机端口，服务器一行配置都不用改，也不用把 3306 暴露到公网。
    # 关掉它就是裸连 MARIADB_HOST:MARIADB_PORT（前提：你已改 bind-address + 放行安全组）。
    mariadb_ssh_tunnel: bool = False
    mariadb_ssh_host: str = ""      # 留空则复用 ssh_host
    mariadb_ssh_port: int = 22
    mariadb_ssh_user: str = ""      # 留空则复用 ssh_user
    mariadb_ssh_password: str = ""  # 留空则复用 ssh_password

    # 安全管控
    risk_amount_threshold: float = 50.0
    confirm_timeout_min: int = 30

    # 账号鉴权（开发环境请通过 .env 覆盖 JWT_SECRET）
    jwt_secret: str = ""
    jwt_access_minutes: int = 30
    jwt_refresh_days: int = 30

    # 调试开关：/seed 等危险演示端点的门禁。开发默认开；部署时在 .env 里
    # 显式写 DEBUG=false 关掉 —— 开着它等于把"重置全库"挂在公网上。
    debug: bool = True

    # 高德开放平台
    amap_web_key: str = "c260220fcc8a09359fa5ddd54f575cf1"
    amap_js_key: str = "706804e5a0a33cdf140126d75bedd3ac"
    amap_security_code: str = "6c6e8eddf72527878c4eb76d7273e380"

    # 智能体预算（三级止损：步数在 Agent 类上，token / 墙钟在这儿）
    budget_max_tokens: int = 60_000
    budget_wall_clock_s: float = 90.0
    tool_timeout_s: float = 20.0
    tool_concurrency: int = 4


settings = Settings()
