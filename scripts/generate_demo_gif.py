import os
import sys
from PIL import Image, ImageDraw, ImageFont

# Set up dimensions and colors
WIDTH = 800
HEIGHT = 500
BG_COLOR = (15, 20, 25)        # Dark blue-gray (#0f1419)
TEXT_COLOR = (217, 223, 228)    # Light gray (#d9dfe4)
PROMPT_COLOR = (59, 142, 234)   # Blue (#3b8eea)
CMD_COLOR = (255, 255, 255)     # Pure White
GREEN_COLOR = (149, 230, 203)   # Mint Green
YELLOW_COLOR = (255, 179, 102)  # Orange/Yellow
RED_COLOR = (255, 102, 102)     # Red
BORDER_COLOR = (26, 32, 44)     # Border
BAR_COLOR = (22, 26, 33)        # Title bar background

# Load Consolas font
try:
    font = ImageFont.truetype("consolas.ttf", 15)
    bold_font = ImageFont.truetype("consolas.ttf", 15)
except IOError:
    # Fallback to load default font if Consolas is somehow missing
    font = ImageFont.load_default()
    bold_font = ImageFont.load_default()

LINE_HEIGHT = 20
TOP_MARGIN = 40
LEFT_MARGIN = 20

def draw_window_frame(draw):
    # Title bar
    draw.rectangle([0, 0, WIDTH, TOP_MARGIN], fill=BAR_COLOR)
    # Window controls (Red, Yellow, Green dots)
    draw.ellipse([15, 13, 27, 25], fill=(255, 95, 87))
    draw.ellipse([35, 13, 47, 25], fill=(254, 188, 46))
    draw.ellipse([55, 13, 67, 25], fill=(40, 200, 64))
    # Title text
    title_text = "mcp-debugger -- terminal demo"
    w = draw.textlength(title_text, font=font)
    draw.text(((WIDTH - w) // 2, 10), title_text, fill=(110, 118, 129), font=font)

def create_frame(lines):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_window_frame(draw)
    
    y = TOP_MARGIN + 15
    for line in lines:
        if isinstance(line, list):
            # Rich multi-color line formatting
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
    
    # 1. Starting empty prompt
    prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines = [prompt]
    # Stay for 10 frames
    for _ in range(5):
        frames.append((create_frame(lines), 200))
        
    # 2. Type "pip install mcp-debugger"
    cmd = "pip install mcp-debugger"
    for i in range(len(cmd) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd[:i], CMD_COLOR)]
        if i < len(cmd):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame([current_prompt]), 80))
        
    # Add a delay after command entry
    last_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd, CMD_COLOR)]
    frames.append((create_frame([last_prompt]), 500))
    
    # 3. Installation output
    install_lines = [
        last_prompt,
        "Collecting mcp-debugger...",
        "  Downloading mcp_debugger-0.1.0-py3-none-any.whl (66.6 kB)",
        "Installing collected packages: mcp-debugger",
        [("Successfully installed mcp-debugger-0.1.0", GREEN_COLOR)]
    ]
    frames.append((create_frame(install_lines), 2000))
    
    # 4. Prompt for doctor command
    doctor_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines = install_lines + [doctor_prompt]
    frames.append((create_frame(lines), 300))
    
    cmd_doc = "mcp-debugger doctor"
    for i in range(len(cmd_doc) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_doc[:i], CMD_COLOR)]
        if i < len(cmd_doc):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(install_lines + [current_prompt]), 80))
        
    last_doctor_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_doc, CMD_COLOR)]
    frames.append((create_frame(install_lines + [last_doctor_prompt]), 600))
    
    # 5. Doctor output (scrolled)
    doctor_lines = [
        last_doctor_prompt,
        "+- MCP Debugger Environment Check --------------------------------------------+",
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" Python version: 3.12.0 (required >=3.11)                                 |", TEXT_COLOR)],
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" SQLite version: 3.42.0                                                   |", TEXT_COLOR)],
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" Database directory: C:\\Users\\Sushant512\\.mcp-debugger [writable]         |", TEXT_COLOR)],
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" Database file: C:\\Users\\Sushant512\\.mcp-debugger\\sessions.db [exists]    |", TEXT_COLOR)],
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" Database schema version: 1                                               |", TEXT_COLOR)],
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" npx command found: C:\\Program Files\\nodejs\\npx (for Node.js)           |", TEXT_COLOR)],
        [("| ", TEXT_COLOR), ("OK", GREEN_COLOR), (" Node.js found: C:\\Program Files\\nodejs\\node.EXE                          |", TEXT_COLOR)],
        "+-----------------------------------------------------------------------------+"
    ]
    frames.append((create_frame(doctor_lines), 2500))
    
    # 6. Prompt for validate command (Scroll everything up)
    validate_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR)]
    lines = doctor_lines[-6:] + [validate_prompt]
    frames.append((create_frame(lines), 300))
    
    cmd_val = "mcp-debugger validate --session 1"
    for i in range(len(cmd_val) + 1):
        current_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_val[:i], CMD_COLOR)]
        if i < len(cmd_val):
            current_prompt.append(("_", CMD_COLOR))
        frames.append((create_frame(doctor_lines[-6:] + [current_prompt]), 80))
        
    last_validate_prompt = [("C:\\Users\\sushant> ", PROMPT_COLOR), (cmd_val, CMD_COLOR)]
    frames.append((create_frame(doctor_lines[-6:] + [last_validate_prompt]), 600))
    
    # 7. Validate output
    validate_lines = doctor_lines[-6:] + [
        last_validate_prompt,
        "Validating recorded session #1...",
        "  - Check handshake order: [PASS]",
        "  - Validate JSON-RPC structure: [PASS]",
        "  - Check error schemas: [PASS]",
        [("Protocol validation: SUCCESS (0 errors, 0 warnings)", GREEN_COLOR)]
    ]
    frames.append((create_frame(validate_lines), 2500))
    
    # Save the GIF
    os.makedirs("docs", exist_ok=True)
    gif_path = "docs/demo.gif"
    
    img_list = [f[0] for f in frames]
    durations = [f[1] for f in frames]
    
    print(f"Saving GIF to {gif_path} ({len(img_list)} frames)...")
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
