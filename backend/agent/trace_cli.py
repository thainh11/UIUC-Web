"""Read chat traces from Postgres.

    python -m backend.agent.trace_cli tail [-n 20] [--status error]   # newest first, one line each
    python -m backend.agent.trace_cli show <id>                       # header, span timeline, payload if stored
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from psycopg.rows import dict_row
import psycopg

SKIP = {"name", "start_ms", "ms"}


def connect() -> psycopg.Connection:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL missing (see .env.example)")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def tail(conn: psycopg.Connection, limit: int, status: str | None) -> None:
    rows = conn.execute(
        """SELECT id, created_at, status, duration_ms, attrs FROM chat_traces
           WHERE (%s::text IS NULL OR status = %s) ORDER BY created_at DESC LIMIT %s""",
        [status, status, limit],
    ).fetchall()
    for row in rows:
        a = row["attrs"]
        print(
            f"{row['id']}  {row['created_at']:%m-%d %H:%M:%S}  {row['status']:<7} {row['duration_ms']:>6}ms"
            f"  rounds={a.get('rounds')} tools={a.get('tool_calls')} ctx={'y' if a.get('context') else 'n'} known={a.get('known')}"
        )


def show(conn: psycopg.Connection, trace_id: str) -> None:
    row = conn.execute("SELECT * FROM chat_traces WHERE id = %s", [trace_id]).fetchone()
    if row is None:
        sys.exit(f"no trace {trace_id}")
    print(f"{row['id']}  {row['created_at']}  {row['status']}  {row['duration_ms']}ms")
    print(json.dumps(row["attrs"], ensure_ascii=False))
    for span in row["spans"]:
        extra = {k: v for k, v in span.items() if k not in SKIP}
        print(f"  {span['start_ms']:>6}ms +{span['ms']:>5}ms  {span['name']:<18} {json.dumps(extra, ensure_ascii=False)}")
    if row["payload"]:
        print("payload:")
        for message in row["payload"]:
            print(f"  [{message['role']}] {str(message.get('content'))[:2000]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    tail_parser = sub.add_parser("tail")
    tail_parser.add_argument("-n", type=int, default=20)
    tail_parser.add_argument("--status", choices=["ok", "error", "aborted"])
    sub.add_parser("show").add_argument("id")
    args = parser.parse_args()
    with connect() as conn:
        if args.command == "tail":
            tail(conn, args.n, args.status)
        else:
            show(conn, args.id)


if __name__ == "__main__":
    main()
