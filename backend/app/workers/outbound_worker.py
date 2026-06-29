import argparse
import logging
import time

from app.db.session import SessionLocal
from app.services.outbound_queue import pop_outbound_task
from app.services.outbound_runner import run_outbound_task

logger = logging.getLogger(__name__)


def process_once(timeout_seconds: int = 5) -> bool:
    task_id = pop_outbound_task(timeout_seconds=timeout_seconds)
    if not task_id:
        return False

    with SessionLocal() as db:
        run_outbound_task(task_id, db)
    logger.info("processed outbound task %s", task_id)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="AI ACQ outbound call worker")
    parser.add_argument("--once", action="store_true", help="Process one queued task and exit")
    parser.add_argument("--timeout", type=int, default=5, help="Redis BLPOP timeout in seconds")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Sleep seconds after an empty poll")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        processed = process_once(timeout_seconds=args.timeout)
        if args.once:
            break
        if not processed:
            time.sleep(args.idle_sleep)


if __name__ == "__main__":
    main()
