from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from app.core.config import settings

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-worker")


def _enqueue_with_rq(log_id: int, delay_minutes: int) -> bool:
    if not settings.REDIS_URL:
        return False
    try:
        from redis import Redis
        from rq import Queue
    except Exception:
        return False

    queue = Queue(settings.EMAIL_QUEUE_NAME, connection=Redis.from_url(settings.REDIS_URL))
    if delay_minutes > 0:
        queue.enqueue_in(timedelta(minutes=delay_minutes), send_email_log, log_id)
    else:
        queue.enqueue(send_email_log, log_id)
    return True


def enqueue_email_log(log_id: int, delay_minutes: int = 0) -> None:
    backend = settings.EMAIL_QUEUE_BACKEND.strip().lower()
    if backend in {"auto", "rq"} and _enqueue_with_rq(log_id, delay_minutes):
        return

    if delay_minutes > 0:
        logger.info("Email log %s scheduled in database for %s minute(s).", log_id, delay_minutes)
        return

    _executor.submit(send_email_log, log_id)


def send_email_log(log_id: int) -> None:
    from app.core.database import SessionLocal
    from app.modules.email.service import EmailAutomationService

    db = SessionLocal()
    try:
        EmailAutomationService(db).process_queued_email(log_id)
    finally:
        db.close()


def process_due_scheduled_emails(limit: int = 50) -> int:
    from app.core.database import SessionLocal
    from app.modules.email.service import EmailAutomationService

    db = SessionLocal()
    try:
        return EmailAutomationService(db).process_due_scheduled_emails(limit=limit)
    finally:
        db.close()
