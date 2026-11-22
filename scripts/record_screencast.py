"""Automated End-to-End Real Screencast Pipeline & Transcoder for mcp-debugger.

Drives headless Chrome via Playwright, records the live Web UI & Multi-Agent Flow,
and produces:
- docs/demo.mp4 (High-definition authentic video demo)
- docs/demo.gif (Crisp, optimized fast-paced animated GIF for README)
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

try:
    import imageio.v3 as iio
    import numpy as np
    from PIL import Image
    from playwright.sync_api import sync_playwright
except ImportError:
    iio = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]

from rich.console import Console

from mcp_debugger.live import LiveDashboard

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FRAMES_DIR = Path("scratch/playwright_frames")


def capture_tui_frame(db_path: str = "demo_multi_agent.db") -> Path:
    """Render Terminal TUI dashboard to HTML."""
    console = Console(record=True, width=110)
    dash = LiveDashboard(1, db_path=db_path, console=console)
    asyncio.run(dash.render_once())
    html_content = console.export_html(inline_styles=True)

    # Style as dark Tokyo Night terminal window
    html_content = html_content.replace(
        "background-color: #ffffff;",
        "background-color: #1a1b26; padding: 30px; font-family: monospace;",
    )
    html_content = html_content.replace("color: #000000;", "color: #c0caf5;")

    tui_path = Path("scratch/live_tui.html")
    tui_path.parent.mkdir(parents=True, exist_ok=True)
    tui_path.write_text(html_content, encoding="utf-8")
    return tui_path


def run_screencast_capture(server_url: str = "http://127.0.0.1:8080") -> None:
    """Drive browser, capture authentic UI interactions, and compile demo assets."""
    if sync_playwright is None:
        raise RuntimeError("playwright is required for screencast capture.")

    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    tui_path = capture_tui_frame()

    captured_frames: list[tuple[Path, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH, headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        # 1. Sessions List Overview
        page.goto(f"{server_url}/")
        page.wait_for_selector("tbody tr", timeout=5000)
        time.sleep(1.0)
        f1 = FRAMES_DIR / "01_sessions_overview.png"
        page.screenshot(path=str(f1))
        captured_frames.append((f1, 2000))

        # 2. Navigate to Session #1 Detail
        page.goto(f"{server_url}/session/1")
        page.wait_for_selector("#headerName", timeout=5000)
        time.sleep(1.0)
        f2 = FRAMES_DIR / "02_session_detail_overview.png"
        page.screenshot(path=str(f2))
        captured_frames.append((f2, 2000))

        # 3. Click Tools tab
        page.click('button[data-tab="tools"]')
        time.sleep(1.0)
        f3 = FRAMES_DIR / "03_tools_inspection.png"
        page.screenshot(path=str(f3))
        captured_frames.append((f3, 1800))

        # 4. Click Multi-Agent Flow tab
        page.click('button[data-tab="agents"]')
        page.wait_for_selector(".agent-card", timeout=5000)
        time.sleep(1.2)
        f4 = FRAMES_DIR / "04_agent_flow_topology.png"
        page.screenshot(path=str(f4))
        captured_frames.append((f4, 2500))

        # 5. Filter to SecurityResearcher
        page.click('.agent-card[data-agent-name="SecurityResearcher"]')
        time.sleep(1.0)
        f5 = FRAMES_DIR / "05_filter_security_researcher.png"
        page.screenshot(path=str(f5))
        captured_frames.append((f5, 2200))

        # 6. Filter to PatchGenerator
        page.click('.agent-card[data-agent-name="PatchGenerator"]')
        time.sleep(1.0)
        f6 = FRAMES_DIR / "06_filter_patch_generator.png"
        page.screenshot(path=str(f6))
        captured_frames.append((f6, 2200))

        # 7. Render Terminal TUI Dashboard
        page.goto(tui_path.resolve().as_uri())
        time.sleep(0.8)
        f7 = FRAMES_DIR / "07_terminal_tui_dashboard.png"
        page.screenshot(path=str(f7))
        captured_frames.append((f7, 2500))

        browser.close()

    assemble_media_assets(captured_frames)


def assemble_media_assets(scenes: list[tuple[Path, int]]) -> None:
    """Combine scene snapshots into high-FPS GIF and MP4 assets."""
    if iio is None or Image is None or np is None:
        raise RuntimeError("imageio, imageio-ffmpeg, and pillow are required.")

    target_width = 864
    fps = 10
    gif_frames = []
    durations = []
    video_frames_rgb = []

    for path, duration_ms in scenes:
        img = Image.open(path).convert("RGB")
        aspect = img.height / img.width
        target_height = int(target_width * aspect)
        target_height = (target_height // 16) * 16
        img_resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        q_frame = img_resized.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        gif_frames.append(q_frame)
        durations.append(duration_ms)

        ticks = int((duration_ms / 1000.0) * fps)
        frame_np = np.array(img_resized)
        for _ in range(ticks):
            video_frames_rgb.append(frame_np)

    gif_path = Path("docs/demo.gif")
    mp4_path = Path("docs/demo.mp4")

    gif_frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"docs/demo.gif created ({gif_path.stat().st_size:,} bytes)")

    iio.imwrite(str(mp4_path), video_frames_rgb, fps=fps)
    print(f"docs/demo.mp4 created ({mp4_path.stat().st_size:,} bytes)")


async def seed_demo_database(db_path: str = "demo_multi_agent.db") -> None:
    """Seed comprehensive multi-agent traces and sessions for live recording."""
    from examples.demo_multi_agent_tracing import run_simulation
    from mcp_debugger.storage.database import Database

    print(f"Seeding demo sessions in {db_path}...")
    await run_simulation(db_path=db_path)

    db = Database(db_path=db_path)
    await db.connect()
    try:
        s2 = await db.create_session(
            server_command="npx @modelcontextprotocol/server-filesystem D:/workspace",
            friendly_name="Claude Code Filesystem Workspace Inspection",
            server_name="filesystem-mcp",
        )
        await db.log_message(s2, "client_to_server", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        await db.log_message(
            s2,
            "server_to_client",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"tools": [{"name": "read_file"}, {"name": "write_file"}, {"name": "list_directory"}]},
            },
        )

        s3 = await db.create_session(
            server_command="uv run mcp-server-postgres postgresql://localhost/analytics",
            friendly_name="Production Query Diagnostic & Trace",
            server_name="postgres-mcp",
        )
        await db.log_message(
            s3,
            "client_to_server",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "query", "arguments": {"sql": "SELECT COUNT(*) FROM users"}}},
        )
    finally:
        await db.close()
    print("Database seeding completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record real screencast and convert to GIF.")
    parser.add_argument("--record", action="store_true", help="Record live Web UI via Playwright")
    parser.add_argument("--seed", action="store_true", help="Seed demo_multi_agent.db")
    args = parser.parse_args()

    if args.seed:
        asyncio.run(seed_demo_database())
        return

    if args.record:
        run_screencast_capture()
        return

    # Default action if no args
    run_screencast_capture()


if __name__ == "__main__":
    main()
