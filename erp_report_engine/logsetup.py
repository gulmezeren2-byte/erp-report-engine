"""Logging: human-readable lines on stderr, optional JSONL to a file, a run_id
bound to every record. stdout stays reserved for the machine-readable result
document (so `erp-report-engine run ... | jq` keeps working)."""

from __future__ import annotations

import json
import logging
import sys
import uuid

LOGGER = "erp_report_engine"


class _JsonLines(logging.Formatter):
    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "run_id": self.run_id,
            "event": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(verbose: bool = False, log_file: str | None = None) -> str:
    """Set up logging and return a short run_id bound to every record."""
    run_id = uuid.uuid4().hex[:12]
    logger = logging.getLogger(LOGGER)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(logging.Formatter(f"%(asctime)s [{run_id}] %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(stderr)

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(_JsonLines(run_id))
        logger.addHandler(fh)

    return run_id
