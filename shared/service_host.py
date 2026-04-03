from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from flask import Response, redirect, request, send_from_directory
from jinja2 import ChoiceLoader, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_root_flask_app():
    module_name = f"mossan_store_root_app_{id(object())}"

    app_path = REPO_ROOT / "app.py"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load root app module from {app_path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    create_app = getattr(module, "create_app", None)
    if callable(create_app):
        return create_app()
    return module.app


def _normalize_prefixes(prefixes):
    normalized = []
    for prefix in prefixes:
        cleaned = prefix.rstrip("/")
        normalized.append(cleaned or "/")
    return tuple(normalized)


def _normalize_exact_paths(paths):
    normalized = set()
    for path in paths:
        cleaned = path.rstrip("/")
        normalized.add(cleaned or "/")
    return normalized


def _path_is_allowed(path, *, allowed_prefixes, allowed_exact_paths):
    normalized_path = path.rstrip("/") or "/"
    if normalized_path in allowed_exact_paths:
        return True
    for prefix in allowed_prefixes:
        if prefix == "/":
            return True
        if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
            return True
    return False


def configure_path_gate(app, *, allowed_prefixes=(), allowed_exact_paths=(), root_redirect_to=None):
    normalized_prefixes = _normalize_prefixes(allowed_prefixes)
    normalized_exact_paths = _normalize_exact_paths(allowed_exact_paths)

    @app.before_request
    def _restrict_paths_for_service():
        normalized_path = request.path.rstrip("/") or "/"

        if normalized_path == "/" and root_redirect_to:
            return redirect(root_redirect_to)

        if _path_is_allowed(
            normalized_path,
            allowed_prefixes=normalized_prefixes,
            allowed_exact_paths=normalized_exact_paths,
        ):
            return None

        return Response("Not Found", status=404, content_type="text/plain; charset=utf-8")

    return app


def configure_service_asset_overrides(app, *, service_root):
    service_root = Path(service_root)
    service_templates = service_root / "templates"
    service_static = service_root / "static"

    if service_templates.exists():
        existing_loader = app.jinja_loader
        override_loader = FileSystemLoader(str(service_templates))
        if existing_loader is None:
            app.jinja_loader = override_loader
        else:
            app.jinja_loader = ChoiceLoader([override_loader, existing_loader])

    @app.before_request
    def _serve_service_static_override():
        normalized_path = request.path.rstrip("/") or "/"
        if normalized_path == "/favicon.ico":
            favicon_candidate = service_static / "favicon.ico"
            if favicon_candidate.is_file():
                return send_from_directory(service_static, "favicon.ico")
            return None

        if not normalized_path.startswith("/static/"):
            return None

        relative_path = normalized_path.removeprefix("/static/").strip()
        if not relative_path:
            return None

        candidate = service_static / relative_path
        if candidate.is_file():
            return send_from_directory(service_static, relative_path)
        return None

    return app


def build_store_web_app():
    app = load_root_flask_app()
    configure_service_asset_overrides(app, service_root=REPO_ROOT / "services" / "store-web")
    return configure_path_gate(
        app,
        allowed_prefixes=(
            "/static",
            "/blog",
        ),
        allowed_exact_paths=(
            "/",
            "/contact",
            "/apps",
            "/apps/shift",
            "/apps/qrcode",
            "/apps/noticeboard",
            "/apps/attendance/app/description",
            "/robots.txt",
            "/sitemap.xml",
            "/favicon.ico",
        ),
    )


def build_attendance_app():
    app = load_root_flask_app()
    configure_service_asset_overrides(app, service_root=REPO_ROOT / "services" / "attendance-app")
    return configure_path_gate(
        app,
        allowed_prefixes=(
            "/static",
            "/admin",
            "/site-admin",
            "/team",
            "/apps/attendance/app",
            "/apps/attendance/share",
        ),
        allowed_exact_paths=(
            "/favicon.ico",
        ),
        root_redirect_to="/admin/login",
    )
