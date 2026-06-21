#!/usr/bin/env python3
"""
Stress test for mcp-debugger database performance.

Tests:
  1. Batch write throughput: log 1000 notifications via the batch buffer
  2. Sequential write throughput: log 1000 notifications via direct INSERT
  3. Streaming read: iterate 1000 messages via iter_messages()
  4. Bulk read: get all 1000 messages via get_messages()

Usage:
  python scripts/stress_test.py
  python scripts/stress_test.py --messages 5000
  python scripts/stress_test.py --quick    # 200 messages, fast CI mode
"""

import asyncio
import argparse
import sys
import tempfile
import time
from pathlib import Path

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_debugger.storage.database import Database


def make_notification(i: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {"progress": i, "total": 1000, "token": f"tok-{i}"},
    }


async def run_stress(n_messages: int) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "stress_test.db")
        db = Database(db_path=db_path)
        await db.connect()

        session_id = await db.create_session("stress-test-server", friendly_name="stress")

        # ----------------------------------------------------------------
        # 1. Batch write throughput
        # ----------------------------------------------------------------
        print(f"\n{'=' * 60}")
        print(f"Batch write: {n_messages} notifications")
        db.start_flush_task()
        t0 = time.perf_counter()
        for i in range(n_messages):
            await db.log_message(session_id, "client_to_server", make_notification(i))
        await db.stop_flush_task()
        batch_elapsed = time.perf_counter() - t0
        batch_rate = n_messages / batch_elapsed
        print(f"  Time:  {batch_elapsed:.3f}s")
        print(f"  Rate:  {batch_rate:,.0f} msg/s")

        # Verify count
        messages = await db.get_messages(session_id)
        assert len(messages) == n_messages, f"Expected {n_messages}, got {len(messages)}"
        print(f"  Verified {len(messages)} messages in DB [OK]")

        # ----------------------------------------------------------------
        # 2. Sequential write throughput (control group)
        # ----------------------------------------------------------------
        session_id2 = await db.create_session("stress-test-server", friendly_name="stress-seq")
        print(f"\n{'=' * 60}")
        print(f"Sequential write: {n_messages} notifications")
        t0 = time.perf_counter()
        for i in range(n_messages):
            await db.log_message(session_id2, "client_to_server", make_notification(i))
        seq_elapsed = time.perf_counter() - t0
        seq_rate = n_messages / seq_elapsed
        print(f"  Time:  {seq_elapsed:.3f}s")
        print(f"  Rate:  {seq_rate:,.0f} msg/s")

        speedup = seq_elapsed / batch_elapsed if batch_elapsed > 0 else float("inf")
        print(f"\n  Batch speedup: {speedup:.1f}x over sequential")

        # ----------------------------------------------------------------
        # 3. Streaming read via iter_messages()
        # ----------------------------------------------------------------
        print(f"\n{'=' * 60}")
        print(f"Streaming read: iter_messages() over {n_messages} rows")
        t0 = time.perf_counter()
        count = 0
        async for _ in db.iter_messages(session_id):
            count += 1
        stream_elapsed = time.perf_counter() - t0
        print(f"  Streamed {count} messages in {stream_elapsed:.3f}s")
        assert count == n_messages, f"Expected {n_messages} streamed, got {count}"
        print(f"  [OK] All {count} messages streamed correctly")

        # ----------------------------------------------------------------
        # 4. Bulk read via get_messages()
        # ----------------------------------------------------------------
        print(f"\n{'=' * 60}")
        print(f"Bulk read: get_messages() over {n_messages} rows")
        t0 = time.perf_counter()
        bulk = await db.get_messages(session_id)
        bulk_elapsed = time.perf_counter() - t0
        print(f"  Fetched {len(bulk)} messages in {bulk_elapsed:.3f}s")
        assert len(bulk) == n_messages

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        print(f"\n{'=' * 60}")
        print("SUMMARY")
        print(f"  Messages:         {n_messages}")
        print(f"  Batch write:      {batch_rate:>10,.0f} msg/s  ({batch_elapsed:.3f}s)")
        print(f"  Sequential write: {seq_rate:>10,.0f} msg/s  ({seq_elapsed:.3f}s)")
        print(
            f"  Streaming read:   {count / stream_elapsed:>10,.0f} msg/s  ({stream_elapsed:.3f}s)"
        )
        print(
            f"  Bulk read:        {n_messages / bulk_elapsed:>10,.0f} msg/s  ({bulk_elapsed:.3f}s)"
        )
        print(f"  Batch speedup:    {speedup:.1f}x")
        print(f"{'=' * 60}\n")

        if batch_rate < 500:
            print("WARNING: Batch write rate below 500 msg/s -- check disk I/O.")
        else:
            print("[OK] Performance benchmarks passed.")

        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="mcp-debugger database stress test")
    parser.add_argument(
        "--messages", type=int, default=1000, help="Number of messages to write (default: 1000)"
    )
    parser.add_argument("--quick", action="store_true", help="Quick mode: 200 messages (for CI)")
    args = parser.parse_args()

    n = 200 if args.quick else args.messages
    print(f"mcp-debugger stress test  |  messages={n}")
    asyncio.run(run_stress(n))


if __name__ == "__main__":
    main()
