import os
import sys
from PIL import Image, ImageDraw, ImageFont

# Set up dimensions and colors
WIDTH = 800
HEIGHT = 560
BG_COLOR = (26, 27, 38)         # Tokyo Night dark (#1a1b26)
TEXT_COLOR = (201, 233, 244)    # Ice blue (#c9e9f4)
PROMPT_COLOR = (122, 162, 247)  # Tokyo Night prompt blue (#7aa2f7)
CMD_COLOR = (255, 255, 255)     # Pure White
GREEN_COLOR = (158, 206, 106)   # Tokyo Night Green (#9ece6a)
YELLOW_COLOR = (224, 175, 104)  # Tokyo Night Yellow (#e0af68)
RED_COLOR = (247, 118, 142)     # Tokyo Night Red (#f7768e)
CYAN_COLOR = (125, 207, 255)    # Cyan
BORDER_COLOR = (65, 72, 104)    # Border color (#414868)
BAR_COLOR = (22, 22, 30)        # Title bar background (#16161e)

# Banner settings
BANNER_BG = (88, 86, 214)       # Indigo (#5856d6)
BANNER_TEXT = (255, 255, 255)

# Load fonts
try:
    font = ImageFont.truetype("consolas.ttf", 14)
    bold_font = ImageFont.truetype("consolas.ttf", 14)
    banner_font = ImageFont.truetype("arial.ttf", 15)
except IOError:
    font = ImageFont.load_default()
    bold_font = ImageFont.load_default()
    banner_font = ImageFont.load_default()

LINE_HEIGHT = 20
TOP_MARGIN = 40
LEFT_MARGIN = 25
BOTTOM_BANNER_HEIGHT = 45

def draw_window_decorations(draw, explanation):
    # Outer border
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=BORDER_COLOR, width=2)
    
    # Title bar
    draw.rectangle([2, 2, WIDTH - 3, TOP_MARGIN], fill=BAR_COLOR)
    
    # Window controls (macOS style window dots)
    draw.ellipse([15, 13, 27, 25], fill=(247, 118, 142))  # Red
    draw.ellipse([35, 13, 47, 25], fill=(224, 175, 104))  # Yellow
    draw.ellipse([55, 13, 67, 25], fill=(158, 206, 106))  # Green
    
    # Title text
    title_text = "mcp-debugger -- Interactive Demo"
    w = draw.textlength(title_text, font=font)
    draw.text(((WIDTH - w) // 2, 12), title_text, fill=(86, 95, 137), font=bold_font)
    
    # Bottom explanation banner
    draw.rectangle([2, HEIGHT - BOTTOM_BANNER_HEIGHT - 2, WIDTH - 3, HEIGHT - 3], fill=BANNER_BG)
    # Banner text centered
    w_exp = draw.textlength(explanation, font=banner_font)
    draw.text(((WIDTH - w_exp) // 2, HEIGHT - BOTTOM_BANNER_HEIGHT + 12), explanation, fill=BANNER_TEXT, font=banner_font)

def create_frame(lines, explanation):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_window_decorations(draw, explanation)
    
    y = TOP_MARGIN + 20
    for line in lines:
        if isinstance(line, list):
            x = LEFT_MARGIN
            for chunk, color in line:
                draw.text((x, y), chunk, fill=color, font=font)
                x += draw.textlength(chunk, font=font)
        else:
            draw.text((LEFT_MARGIN, y), line, fill=TEXT_COLOR, font=font)
        y += LINE_HEIGHT
        
    return img

def main():
    print("Generating frames...")
    frames = []
    
    # ----------------------------------------------------
    # PHASE 1: Quick Install
    # ----------------------------------------------------
    exp_1 = "📦 Step 1: Install mcp-debugger via pip"
    prompt_1 = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines = [prompt_1]
    
    # Empty prompt delay
    for _ in range(3):
        frames.append((create_frame(lines, exp_1), 150))
        
    # Typing command
    cmd_1 = "pip install mcp-debugger"
    for i in range(len(cmd_1) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_1[:i], CMD_COLOR)]
        if i < len(cmd_1):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame([current_prompt], exp_1), 60))
        
    # Submitted command
    last_prompt_1 = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_1, CMD_COLOR)]
    frames.append((create_frame([last_prompt_1], exp_1), 400))
    
    # Installation progress and completion
    install_lines = [
        last_prompt_1,
        "Collecting mcp-debugger",
        "  Downloading mcp_debugger-0.1.0-py3-none-any.whl (66.7 kB)",
        "Installing collected packages: mcp-debugger",
        [("Successfully installed mcp-debugger-0.1.0", GREEN_COLOR)]
    ]
    frames.append((create_frame(install_lines, exp_1), 1500))
    
    # ----------------------------------------------------
    # PHASE 2: Doctor Check (Diagnose environment)
    # ----------------------------------------------------
    exp_2 = "🩺 Step 2: Run diagnostic suite to check environment requirements"
    prompt_2 = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines_2 = install_lines + [prompt_2]
    frames.append((create_frame(lines_2, exp_2), 200))
    
    cmd_2 = "mcp-debugger doctor"
    for i in range(len(cmd_2) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_2[:i], CMD_COLOR)]
        if i < len(cmd_2):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(install_lines + [current_prompt], exp_2), 60))
        
    last_prompt_2 = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_2, CMD_COLOR)]
    frames.append((create_frame(install_lines + [last_prompt_2], exp_2), 400))
    
    # Draw doctor panel report
    doc_panel = [
        last_prompt_2,
        [("┌─ ", BORDER_COLOR), ("MCP Debugger Environment Check", CYAN_COLOR), (" ─────────────────────────┐", BORDER_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" Python version: 3.12.0 (required >=3.11)                   │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" SQLite version: 3.42.0                                     │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" Database directory: C:\\Users\\sushant\\.mcp-debugger [writable] │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" Database file: .mcp-debugger\\sessions.db [exists]        │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" Database schema version: 1                                 │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" npx command found: C:\\Program Files\\nodejs\\npx             │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("OK", GREEN_COLOR), (" Node.js found: C:\\Program Files\\nodejs\\node.EXE            │", TEXT_COLOR)],
        [("└─────────────────────────────────────────────────────────────┘", BORDER_COLOR)]
    ]
    frames.append((create_frame(doc_panel, exp_2), 2500))
    
    # ----------------------------------------------------
    # PHASE 3: Proxy — Record a live session
    # ----------------------------------------------------
    exp_3 = "🔴 Step 3: Record live MCP traffic with the transparent proxy"
    prompt_3 = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines_3 = doc_panel[-5:] + [prompt_3]
    frames.append((create_frame(lines_3, exp_3), 200))

    cmd_3 = "mcp-debugger proxy --server \"npx -y @modelcontextprotocol/server-filesystem C:\\temp\" --name my-session"
    for i in range(len(cmd_3) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_3[:i], CMD_COLOR)]
        if i < len(cmd_3):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(doc_panel[-5:] + [current_prompt], exp_3), 45))

    last_prompt_3 = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_3, CMD_COLOR)]
    frames.append((create_frame(doc_panel[-5:] + [last_prompt_3], exp_3), 400))

    proxy_lines = doc_panel[-5:] + [
        last_prompt_3,
        [("Proxy listening — recording session: ", TEXT_COLOR), ("my-session", CYAN_COLOR)],
        "  [client --> server]  initialize",
        "  [server --> client]  initialize response",
        "  [client --> server]  tools/list",
        "  [server --> client]  tools/list response  (3 tools found)",
        "  [client --> server]  tools/call  read_file",
        "  [server --> client]  tools/call result",
        [("  ^C  Session saved. ID: ", TEXT_COLOR), ("#1", YELLOW_COLOR), ("  (8 messages)", TEXT_COLOR)],
    ]
    frames.append((create_frame(proxy_lines, exp_3), 2800))

    # ----------------------------------------------------
    # PHASE 4: Inspect — Browse recorded messages
    # ----------------------------------------------------
    exp_4 = "🔍 Step 4: Inspect every JSON-RPC message between client and server"
    prompt_4 = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines_4 = proxy_lines[-6:] + [prompt_4]
    frames.append((create_frame(lines_4, exp_4), 200))

    cmd_4 = "mcp-debugger inspect 1"
    for i in range(len(cmd_4) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_4[:i], CMD_COLOR)]
        if i < len(cmd_4):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(proxy_lines[-6:] + [current_prompt], exp_4), 80))

    last_prompt_4 = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_4, CMD_COLOR)]
    frames.append((create_frame(proxy_lines[-6:] + [last_prompt_4], exp_4), 400))

    # Inspect panel — show JSON-RPC message details
    inspect_lines = [
        last_prompt_4,
        [("┌─ ", BORDER_COLOR), ("Session #1  my-session  (8 messages)", CYAN_COLOR), (" ─────────────┐", BORDER_COLOR)],
        [("│ ", BORDER_COLOR), ("#1 ", YELLOW_COLOR), ("client-->server  ", TEXT_COLOR), ("initialize", GREEN_COLOR), ("                          │", BORDER_COLOR)],
        [("│   {\"jsonrpc\":\"2.0\",\"method\":\"initialize\",\"id\":1,...}           │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("#2 ", YELLOW_COLOR), ("server-->client  ", TEXT_COLOR), ("initialize result", GREEN_COLOR), ("                    │", BORDER_COLOR)],
        [("│   {\"protocolVersion\":\"2024-11-05\",\"capabilities\":{...}}         │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("#3 ", YELLOW_COLOR), ("client-->server  ", TEXT_COLOR), ("tools/list", GREEN_COLOR), ("                           │", BORDER_COLOR)],
        [("│   {\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":2}               │", TEXT_COLOR)],
        [("│ ", BORDER_COLOR), ("#5 ", YELLOW_COLOR), ("client-->server  ", TEXT_COLOR), ("tools/call  ", GREEN_COLOR), ("read_file", CYAN_COLOR), ("              │", BORDER_COLOR)],
        [("│   {\"name\":\"read_file\",\"arguments\":{\"path\":\"C:\\\\temp\\\\data.txt\"}} │", TEXT_COLOR)],
        [("└─────────────────────────────────────────────────────────────┘", BORDER_COLOR)],
    ]
    frames.append((create_frame(inspect_lines, exp_4), 3200))

    # ----------------------------------------------------
    # PHASE 5: Validate MCP Server
    # ----------------------------------------------------
    exp_5 = "✅ Step 5: Validate live MCP server compliance against spec"
    prompt_5 = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines_5 = inspect_lines[-6:] + [prompt_5]
    frames.append((create_frame(lines_5, exp_5), 200))

    cmd_5 = "mcp-debugger validate --server \"npx -y @modelcontextprotocol/server-filesystem C:\\temp\""
    for i in range(len(cmd_5) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_5[:i], CMD_COLOR)]
        if i < len(cmd_5):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(inspect_lines[-6:] + [current_prompt], exp_5), 50))

    last_prompt_5 = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_5, CMD_COLOR)]
    frames.append((create_frame(inspect_lines[-6:] + [last_prompt_5], exp_5), 400))

    val_lines_base = inspect_lines[-6:] + [last_prompt_5]
    l_1 = val_lines_base + ["Validating live server: npx -y @modelcontextprotocol/server-filesystem C:\\temp"]
    frames.append((create_frame(l_1, exp_5), 300))
    l_2 = l_1 + ["  - Handshake protocol compliance... [PASS]"]
    frames.append((create_frame(l_2, exp_5), 300))
    l_3 = l_2 + ["  - Schema validation of tool definitions... [PASS]"]
    frames.append((create_frame(l_3, exp_5), 300))
    l_4 = l_3 + [
        [("  - Test initialization check... ", TEXT_COLOR), ("OK", GREEN_COLOR)],
        [("Protocol validation: SUCCESS (0 errors, 0 warnings)", GREEN_COLOR)]
    ]
    frames.append((create_frame(l_4, exp_5), 2500))
    
    # ----------------------------------------------------
    # PHASE 6: Replay Session for Regression Tests
    # ----------------------------------------------------
    exp_6 = "🔄 Step 6: Replay recorded sessions to verify response changes"
    prompt_6 = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines_6 = l_4[-6:] + [prompt_6]
    frames.append((create_frame(lines_6, exp_6), 200))

    cmd_6 = "mcp-debugger replay 1 --server \"npx -y @modelcontextprotocol/server-filesystem C:\\temp\""
    for i in range(len(cmd_6) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_6[:i], CMD_COLOR)]
        if i < len(cmd_6):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(l_4[-6:] + [current_prompt], exp_6), 50))

    last_prompt_6 = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_6, CMD_COLOR)]
    frames.append((create_frame(l_4[-6:] + [last_prompt_6], exp_6), 400))

    replay_lines = l_4[-6:] + [
        last_prompt_6,
        "Replaying session #1 against target server...",
        "Replaying tool call: list_templates... [MATCH]",
        "Replaying tool call: get_template... [MATCH]",
        [("┌─ ", BORDER_COLOR), ("Message Replay Summary", CYAN_COLOR), (" ─────────────────────────────┐", BORDER_COLOR)],
        [("│ Total messages replayed: 8                                  │", TEXT_COLOR)],
        [("│ ", TEXT_COLOR), ("OK", GREEN_COLOR), (" Successful matches: 8                                      │", TEXT_COLOR)],
        [("│ ", TEXT_COLOR), ("FAIL", RED_COLOR), (" Mismatches: 0                                              │", TEXT_COLOR)],
        [("└─────────────────────────────────────────────────────────────┘", BORDER_COLOR)]
    ]
    frames.append((create_frame(replay_lines, exp_6), 3000))

    
    # Save GIF
    gif_path = "docs/demo.gif"
    os.makedirs(os.path.dirname(gif_path), exist_ok=True)
    
    img_list = [f[0] for f in frames]
    durations = [f[1] for f in frames]
    
    print(f"Saving high-quality GIF to {gif_path} ({len(img_list)} frames)...")
    img_list[0].save(
        gif_path,
        save_all=True,
        append_images=img_list[1:],
        duration=durations,
        loop=0,
        optimize=True
    )
    print("GIF generated successfully!")

if __name__ == "__main__":
    main()
