"""Paths and JSONL helpers for the gold set."""

from pathlib import Path
import json
import os
import sys

from dotenv import load_dotenv
from psycopg.rows import dict_row
import psycopg

SEED = 20261116
HOLDOUT = 0.3
ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "gold"
WORK = ROOT / "eval" / "work"

LABELER = (
    "Agent làm việc trên repo này chấm nhãn, không dùng endpoint Qwen 27B. "
    "Lúc chấm không nhìn điểm ghép hay phương pháp ghép. "
    "Người phụ trách kiểm lại khoảng 15–20% mẫu, ưu tiên tầng semantic và các cặp unsure."
)


def connect() -> psycopg.Connection:
    load_dotenv()
    url = os.environ.get("DATABASE_URL") or sys.exit("DATABASE_URL missing")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def load_jsonl(path: Path) -> tuple[dict | None, list[dict]]:
    meta = None
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("_meta"):
                meta = obj
            else:
                rows.append(obj)
    return meta, rows


def dump_jsonl(path: Path, meta: dict, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"_meta": True, **meta}, ensure_ascii=False) + "\n"
    payload += "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8")
