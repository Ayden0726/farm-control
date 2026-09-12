from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Print FarmOS"
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    jwt_expire_minutes: int = 60 * 24 * 7
    database_url: str = "postgresql+asyncpg://farmos:farmos@127.0.0.1:5432/farmos"
    redis_url: str = "redis://127.0.0.1:6379/0"
    upload_dir: Path = Path("/workspace/data")
    cors_origins: str = "http://127.0.0.1:43123,http://localhost:43123"
    run_scheduler: bool = True
    scheduler_interval_seconds: float = 2.0
    simulated_time_scale: float = 20.0
    filament_low_grams: float = 150.0
    woocommerce_url: str = ""
    woocommerce_key: str = ""
    woocommerce_secret: str = ""
    public_app_url: str = "http://127.0.0.1:43123"
    app_version: str = "dev"
    update_control_dir: Path = Path("/update-control")
    notify_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "farmos@localhost"
    smtp_to: str = ""
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""
    pushover_app_token: str = ""
    pushover_user_key: str = ""
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    sms_to: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gcode_dir(self) -> Path:
        return self.upload_dir / "gcode"

    @property
    def stl_dir(self) -> Path:
        return self.upload_dir / "stl"

    @property
    def qr_dir(self) -> Path:
        return self.upload_dir / "qr"

    @property
    def qc_dir(self) -> Path:
        return self.upload_dir / "qc"

    @property
    def backup_dir(self) -> Path:
        return self.upload_dir / "backups"

    @property
    def snapshots_dir(self) -> Path:
        return self.upload_dir / "snapshots"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for path in (
        settings.gcode_dir,
        settings.stl_dir,
        settings.qr_dir,
        settings.qc_dir,
        settings.backup_dir,
        settings.snapshots_dir,
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return settings
