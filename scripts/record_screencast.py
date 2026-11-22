"""Automated Screencast Producer & Video-to-GIF Transcoder.

Records real running interactions from mcp-debugger Web UI & CLI,
and generates fast-paced, high-definition assets for documentation:
- docs/demo.mp4 (Full-resolution screencast video)
- docs/demo.gif (Crisp, optimized animated GIF demo replacing synthetic PIL drawing)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from pathlib import Path

try:
    import imageio.v3 as iio
    from PIL import Image
except ImportError:
    iio = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]


def convert_mp4_to_gif(
    mp4_path: str | Path,
    gif_path: str | Path,
    max_width: int = 800,
    fps: int = 12,
    speedup: float = 1.25,
) -> None:
    """Transcode a real MP4 screencast into an optimized, fast-paced animated GIF."""
    if iio is None or Image is None:
        raise RuntimeError("imageio, imageio-ffmpeg, and pillow are required for transcoding.")

    mp4_file = Path(mp4_path)
    if not mp4_file.exists():
        raise FileNotFoundError(f"Source MP4 not found: {mp4_file}")

    print(f"Reading video frames from {mp4_file}...")
    frames = []
    # Read all video frames
    for idx, frame in enumerate(iio.imiter(str(mp4_file))):
        # Sample frames based on speedup factor
        if int(idx * speedup) % int(speedup * 2) == 0 or idx % 2 == 0:
            img = Image.fromarray(frame)
            if img.width > max_width:
                aspect = img.height / img.width
                new_height = int(max_width * aspect)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            # Quantize with adaptive palette for crisp rendering and smaller GIF size
            img_quantized = img.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
            frames.append(img_quantized)

    if not frames:
        raise ValueError("No video frames could be extracted from MP4.")

    print(f"Extracted and downsampled {len(frames)} frames. Encoding animated GIF to {gif_path}...")
    frame_duration_ms = int(1000.0 / fps)
    frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=frames[1:],
        duration=frame_duration_ms,
        loop=0,
        optimize=True,
    )
    print(f"Successfully generated {gif_path} ({os.path.getsize(gif_path):,} bytes)!")


async def seed_demo_database(db_path: str = "demo_multi_agent.db") -> None:
    """Seed comprehensive multi-agent traces and sessions for live recording."""
    from examples.demo_multi_agent_tracing import run_simulation
    from mcp_debugger.storage.database import Database

    print(f"Seeding demo sessions in {db_path}...")
    await run_simulation(db_path=db_path)

    db = Database(db_path=db_path)
    await db.connect()
    try:
        # Session 2: Claude Code Filesystem Workspace Inspection
        s2 = await db.create_session(
            server_command="npx @modelcontextprotocol/server-filesystem D:/workspace",
            friendly_name="Claude Code Filesystem Workspace Inspection",
            server_name="filesystem-mcp",
        )
        await db.log_message(s2, "client_to_server", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        await db.log_message(s2, "server_to_client", {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "read_file"}, {"name": "write_file"}, {"name": "list_directory"}]}})
        await db.log_message(s2, "client_to_server", {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "README.md"}}})
        await db.log_message(s2, "server_to_client", {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "Project Overview"}]}})

        # Session 3: Production Query Diagnostic & Trace
        s3 = await db.create_session(
            server_command="uv run mcp-server-postgres postgresql://localhost/analytics",
            friendly_name="Production Query Diagnostic & Trace",
            server_name="postgres-mcp",
        )
        await db.log_message(s3, "client_to_server", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "query", "arguments": {"sql": "SELECT COUNT(*) FROM users"}}})
        await db.log_message(s3, "server_to_client", {"jsonrpc": "2.0", "id": 1, "result": {"rows": [{"count": 142050}]}})
    finally:
        await db.close()
    print("Database seeding completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record real screencast and convert to GIF.")
    parser.add_argument("--transcode", type=str, help="Transcode an existing MP4 into docs/demo.gif")
    parser.add_argument("--seed", action="store_true", help="Seed demo_multi_agent.db")
    args = parser.parse_args()

    if args.seed:
        asyncio.run(seed_demo_database())
        return

    if args.transcode:
        convert_mp4_to_gif(args.transcode, "docs/demo.gif")
        shutil.copyfile(args.transcode, "docs/demo.mp4")
        return

    print("Use --seed to prepare the database, or --transcode <screencast.mp4> to produce docs/demo.gif & docs/demo.mp4.")


if __name__ == "__main__":
    main()
