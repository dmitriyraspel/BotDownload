"""Central v1 admission rules. Telegram never supplies execution arguments.

This module is the only application-level authority for creating media jobs.
The kernel sandbox remains a separate mandatory deployment prerequisite.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit

from .telegram_handlers import validate_media_url

FORMATS = frozenset(("480p", "720p", "1080p", "MP3"))


class AdmissionDenied(ValueError):
    pass


@dataclass(frozen=True)
class ApprovedInspect:
    url: str


@dataclass(frozen=True)
class ApprovedDownload:
    task_id: int
    url: str
    quality: str


def admit_inspect(url: str) -> ApprovedInspect:
    if not validate_media_url(url):
        raise AdmissionDenied("Недопустимая ссылка")
    return ApprovedInspect(url)


def admit_download(db, *, task_id: int) -> ApprovedDownload:
    """Read the immutable card->task binding, never accept a callback URL.

    This is a local integrity check, not a second network inspection.
    """
    if type(task_id) is not int or task_id <= 0:
        raise AdmissionDenied("Некорректная задача")
    row = db.execute(
        """SELECT t.source_url,t.variant,t.user_id,t.chat_id,t.message_id,
                  t.status,p.source_url,p.available_variants,p.cancelled
           FROM tasks t JOIN previews p
             ON t.chat_id=p.chat_id AND t.message_id=p.message_id
           WHERE t.id=?""", (task_id,)
    ).fetchone()
    if row is None:
        raise AdmissionDenied("Нет утверждённой карточки")
    url, quality, owner, chat, message, status, card_url, variants_json, cancelled = row
    import json
    try:
        variants = json.loads(variants_json)
    except (TypeError, ValueError) as exc:
        raise AdmissionDenied("Повреждены варианты качества") from exc
    card_owner = db.execute(
        "SELECT user_id FROM previews WHERE chat_id=? AND message_id=?",
        (chat, message),
    ).fetchone()
    if (cancelled or card_owner is None or owner != card_owner[0]
            or status not in ("queued", "downloading")
            or quality not in FORMATS or not isinstance(variants, list)
            or quality not in variants or url != card_url
            or not validate_media_url(url)):
        raise AdmissionDenied("Задание не соответствует утверждённой карточке")
    return ApprovedDownload(task_id, url, quality)
