from pathlib import Path
import sys

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from service_modules.store_web_routes import register_store_web_routes
from shared.contact_runtime import (
    build_contact_page_context,
    is_valid_email,
    load_contact_mail_settings,
    send_contact_form_email,
)
from shared.runtime_config import load_default_env_files
from shared.runtime_settings import load_runtime_settings


def create_app():
    load_default_env_files(
        candidate_paths=(
            REPO_ROOT / ".env",
            REPO_ROOT / ".env.local",
            SERVICE_ROOT / ".env",
            SERVICE_ROOT / ".env.local",
        )
    )
    runtime_settings = load_runtime_settings("mossan-store-web")
    contact_mail_settings = load_contact_mail_settings()

    app = Flask(
        __name__,
        template_folder=str(SERVICE_ROOT / "templates"),
        static_folder=str(SERVICE_ROOT / "static"),
    )
    app.secret_key = runtime_settings.secret_key

    register_store_web_routes(
        app,
        attendance_app_base_url=(__import__("os").environ.get("ATTENDANCE_APP_BASE_URL", "").strip()),
        build_contact_page_context=lambda **kwargs: build_contact_page_context(contact_mail_settings, **kwargs),
        is_contact_email_configured=lambda: contact_mail_settings.is_configured,
        is_valid_email=is_valid_email,
        register_attendance_proxy_routes=True,
        send_contact_form_email=lambda **kwargs: send_contact_form_email(contact_mail_settings, **kwargs),
    )
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
