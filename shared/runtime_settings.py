from dataclasses import dataclass
import os

from .runtime_config import resolve_default_sqlite_db_path


@dataclass(frozen=True)
class RuntimeSettings:
    secret_key: str
    database_url: str
    use_postgres: bool
    sqlite_db_path: str
    render_env: bool
    portal_json_migration_enabled: bool


def load_runtime_settings(app_name="mossan-store"):
    database_url = os.environ.get("DATABASE_URL", "").strip()
    return RuntimeSettings(
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        database_url=database_url,
        use_postgres=database_url.startswith(("postgresql://", "postgres://")),
        sqlite_db_path=os.environ.get("SQLITE_DB_PATH", resolve_default_sqlite_db_path(app_name)),
        render_env=os.environ.get("RENDER", "").strip().lower() == "true",
        portal_json_migration_enabled=os.environ.get("PORTAL_JSON_MIGRATION_ENABLED", "").strip() == "1",
    )
