from pathlib import Path
import os
import tempfile


def load_simple_env_file(path):
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def resolve_default_sqlite_db_path(app_name="mossan-store"):
    base_dir = Path(tempfile.gettempdir()) / app_name
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback_dir = Path(".codex_local")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        base_dir = fallback_dir
    return str(base_dir / "schedule.db")


def load_default_env_files(candidate_paths=(".env", ".env.local")):
    for candidate_env_path in candidate_paths:
        load_simple_env_file(candidate_env_path)
