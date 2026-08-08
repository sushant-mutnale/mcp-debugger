Day 26: FastAPI Backend Setup
🎯 Core Objective
Set up the FastAPI web backend that will serve the Web UI. This is the foundation for all web-based features.

By the end of Day 26, you'll have a running web server that can:

List sessions from the database via API.

Serve basic HTML pages.

Provide a foundation for the interactive Web UI.

📦 What You Need to Build
New Dependencies:

fastapi – Web framework

jinja2 – Template engine for HTML

uvicorn – ASGI server

python-multipart – Form parsing

New Directory Structure:

text
src/mcp_debugger/
├── web/
│ ├── **init**.py
│ ├── app.py # FastAPI application
│ ├── templates/ # Jinja2 templates
│ │ ├── base.html
│ │ └── sessions.html
│ └── static/ # CSS, JS, images (optional)
└── cli.py # Add 'web' command
🧠 Expected Behaviour

1. Add Dependencies
   Add FastAPI, Jinja2, Uvicorn, and python-multipart to pyproject.toml:

toml
dependencies = [
# ... existing dependencies ...
"fastapi>=0.110.0",
"jinja2>=3.1.0",
"uvicorn>=0.27.0",
"python-multipart>=0.0.9",
]
Then run: uv sync

2. Create FastAPI Application (src/mcp_debugger/web/app.py)
   This is the main application file. It will:

Create a FastAPI app instance.

Configure Jinja2 templates.

Add CORS middleware (for development).

Define routes:

GET / – Home page (session list)

GET /api/sessions – JSON endpoint for session list

GET /api/sessions/{id} – JSON endpoint for session detail

GET /api/sessions/{id}/messages – JSON endpoint for messages

Route Implementation Details:

Route Method Behaviour
/ GET Renders sessions.html template with session data.
/api/sessions GET Returns JSON array of all sessions (id, name, server_command, started_at, ended_at, status, message_count).
/api/sessions/{id} GET Returns JSON object with session details (metadata + tools + errors + stats).
/api/sessions/{id}/messages GET Returns JSON array of messages with optional filtering (method, direction, limit, offset).
/api/sessions/{id}/export GET Exports session in specified format (format=json|markdown|otlp).
API Response Examples:

GET /api/sessions:

json
[
{
"id": 1,
"friendly_name": "filesystem-test",
"server_command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
"started_at": "2025-06-10T14:23:01",
"ended_at": "2025-06-10T14:25:35",
"status": "completed",
"message_count": 142
}
]
GET /api/sessions/1:

json
{
"id": 1,
"friendly_name": "filesystem-test",
"server_command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
"started_at": "2025-06-10T14:23:01",
"ended_at": "2025-06-10T14:25:35",
"status": "completed",
"total_messages": 142,
"tools": [...],
"errors": [...]
} 3. Create Base Template (templates/base.html)
This is the layout template that all pages will extend. It should include:

HTML5 structure with <head> and <body>.

CSS (use simple or CDN Tailwind).

Header with navigation.

Footer with version info.

Block placeholders: {% block content %} and {% block scripts %}.

4. Create Sessions Template (templates/sessions.html)
   This template extends base.html and:

Displays sessions in a table (ID, Name, Server Command, Started, Duration, Messages, Status).

Status badges: 🟢 Completed, 🟡 Running, 🔴 Error.

Search box (client-side filtering).

Pagination (25 sessions per page).

5. Add web Command to CLI
   Add a new command to cli.py:

bash
mcp-debugger web [--port 8000] [--host 127.0.0.1] [--open]
Starts the Uvicorn server.

--open automatically opens the browser.

Uses the same database as the CLI.

6. Database Helper Functions
   Add new functions to database.py for the web UI:

get_sessions(limit, offset, status) – returns sessions list.

get_session_metadata(session_id) – returns session metadata + stats.

get_session_messages(session_id, method, direction, limit, offset) – returns messages with filters.

get_session_tools(session_id) – returns tools for session.

get_session_errors(session_id) – returns errors for session.

7. Error Handling
   If session ID doesn't exist, return 404 with a JSON error.

If database is missing, show a helpful error message.

Handle malformed requests gracefully.

🔗 Integration with Previous Days
Day 3 (Database): The web APIs will use the same Database class to fetch data.

Day 5 (List): The web session list should match the CLI list command output.

Day 6 (Inspect): The web session detail should match the CLI inspect command output.

Day 13 (Export): The web export endpoint should use the same exporters.

⚙️ Production Considerations
Performance
Session list should load in <500ms for 100+ sessions.

Use indexes on started_at and status for quick sorting.

Use LIMIT and OFFSET for pagination.

For message count, use SELECT COUNT(\*) instead of loading all messages.

CORS
Add CORS middleware for development (allows frontend to call API from different port).

In production, restrict to specific origins.

Security
No authentication yet (Phase 1). The web UI is local-only.

Ensure the web server listens on 127.0.0.1 by default (not exposed to network).

Add --host 0.0.0.0 flag only for advanced users.

Development vs Production
In development, use --reload flag for auto-reload.

In production, use --workers 4 for concurrency.

✅ Day 26 Verification Checklist

# Check How to verify

1 Dependencies installed uv sync – no errors.
2 FastAPI app runs uv run uvicorn src.mcp_debugger.web.app:app --reload – starts without errors.
3 Home page loads Open http://localhost:8000/ – shows a page (even if no sessions).
4 API endpoint works curl http://localhost:8000/api/sessions – returns JSON (empty array if no sessions).
5 Session list page After running a proxy session, / shows sessions in a table.
6 Session detail API curl http://localhost:8000/api/sessions/1 – returns session metadata.
7 mcp-debugger web command works Run mcp-debugger web – server starts.
8 --open flag opens browser Run mcp-debugger web --open – browser opens automatically.
9 Database helper functions work Database.get_sessions() returns sessions list.
10 ruff check passes No linting errors.
11 mypy --strict passes No type errors.
12 Documentation: docs/web-ui.md created Basic setup instructions.
13 Commit with message feat(web): add FastAPI backend for Web UI –
💡 Tips for Day 26
Start with the simplest possible routes – just get / and /api/sessions working.

Use app.mount("/static", StaticFiles(directory="static"), name="static") for CSS/JS.

For the HTML template, use a minimal CSS framework like Pico CSS or Tailwind CDN – don't build custom CSS from scratch.

Test the API endpoints with curl or the browser before building the templates.

Reuse existing Database methods – don't duplicate logic.
