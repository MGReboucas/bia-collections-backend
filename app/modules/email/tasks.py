from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-worker")
_scheduler_stop = threading.Event()
_scheduler_thread: threading.Thread | None = None


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


def purge_expired_email_content() -> int:
    from app.core.database import SessionLocal
    from app.modules.email.service import EmailAutomationService

    db = SessionLocal()
    try:
        return EmailAutomationService(db).purge_expired_log_content()
    finally:
        db.close()


def _scheduler_loop() -> None:
    last_purge_date = None
    interval = max(5, settings.EMAIL_SCHEDULER_INTERVAL_SECONDS)
    while not _scheduler_stop.wait(interval):
        try:
            processed = process_due_scheduled_emails()
            if processed:
                logger.info("Email scheduler enqueued %s due message(s).", processed)
            today = datetime.now(timezone.utc).date()
            if last_purge_date != today:
                purged = purge_expired_email_content()
                if purged:
                    logger.info("Email retention cleared content from %s log(s).", purged)
                last_purge_date = today
        except Exception:
            logger.exception("Email scheduler cycle failed.")


def start_email_scheduler() -> None:
    global _scheduler_thread
    if not settings.EMAIL_SCHEDULER_ENABLED:
        return
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="email-scheduler",
        daemon=True,
    )
    _scheduler_thread.start()


def stop_email_scheduler() -> None:
    global _scheduler_thread
    _scheduler_stop.set()
    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=2)
    _scheduler_thread = None
