from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage


def is_valid_email(value: str) -> bool:
    normalized = (value or "").strip()
    return "@" in normalized and "." in normalized.split("@")[-1]


@dataclass(frozen=True)
class ContactMailSettings:
    to_email: str
    from_email: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool

    @property
    def is_configured(self) -> bool:
        return all(
            (
                self.to_email,
                self.from_email,
                self.smtp_host,
                self.smtp_username,
                self.smtp_password,
            )
        )


def load_contact_mail_settings() -> ContactMailSettings:
    return ContactMailSettings(
        to_email=os.environ.get("CONTACT_FORM_TO_EMAIL", "").strip(),
        from_email=os.environ.get("CONTACT_FORM_FROM_EMAIL", "").strip(),
        smtp_host=os.environ.get("SMTP_HOST", "").strip(),
        smtp_port=int(os.environ.get("SMTP_PORT", "587").strip() or "587"),
        smtp_username=os.environ.get("SMTP_USERNAME", "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD", "").strip(),
        smtp_use_tls=os.environ.get("SMTP_USE_TLS", "1").strip().lower() not in {"0", "false", "no", "off"},
    )


def build_contact_page_context(settings: ContactMailSettings, *, status: str = "", error_message: str = "", prefill=None):
    return {
        "contact_status": status,
        "contact_error_message": error_message,
        "contact_prefill": prefill or {},
        "contact_email_enabled": settings.is_configured,
    }


def send_contact_form_email(
    settings: ContactMailSettings,
    *,
    name: str,
    email: str,
    subject: str,
    message: str,
    remote_addr: str = "",
    user_agent: str = "",
) -> None:
    if not settings.is_configured:
        raise RuntimeError("Contact email is not configured.")

    mail = EmailMessage()
    mail["Subject"] = f"[Mossan Store] {subject}"
    mail["From"] = settings.from_email
    mail["To"] = settings.to_email
    mail["Reply-To"] = email
    mail.set_content(
        "\n".join(
            [
                "Mossan Store の問い合わせフォームから新しいメッセージが届きました。",
                "",
                f"お名前: {name}",
                f"メールアドレス: {email}",
                f"件名: {subject}",
                "",
                "内容:",
                message,
                "",
                f"送信日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"IP: {remote_addr or '-'}",
                f"User-Agent: {user_agent or '-'}",
            ]
        )
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(mail)
