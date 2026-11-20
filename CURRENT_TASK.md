Day 27: Session List View – Making the Web UI Beautiful
You have the FastAPI backend running (Day 26). Now it's time to make it look good and work well for users.

By the end of Day 27, the Web UI will show a polished, functional session list page with:

Beautiful table with all session data.

Status badges with colours.

Search and filtering.

Pagination.

"New Session" button with helpful instructions.

🎯 Core Objective
Build the session list page (/) that displays all recorded sessions in a clean, professional interface.

What users will see:

A table with: ID, Name, Server Command (truncated), Started At, Duration, Messages Count, Status.

Status badges: 🟢 Completed, 🟡 Running, 🔴 Error, ⚪ Unknown.

Search box to filter sessions by name or server command.

Filter by status (dropdown).

Pagination controls (Previous/Next, page numbers).

"Record New Session" button that shows the mcp-debugger proxy command.

Auto-refresh (optional – for running sessions).

📦 What You Need to Build
Component File Description
Base Template templates/base.html Layout with header, navigation, footer, CSS/JS includes
Session List Template templates/sessions.html Main page with table, search, filters, pagination
Static CSS static/style.css Custom styles (or use Tailwind CDN)
Static JS static/app.js Client-side search, filter, pagination logic
API Enhancement app.py Add ?search=, ?status=, ?page=, ?limit= query params
🧠 Expected Behaviour

1. Base Template (templates/base.html)
   Purpose: Common layout for all pages.

Structure:

html

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}MCP Debugger{% endblock %}</title>
    <!-- CSS -->
    <link rel="stylesheet" href="/static/style.css">
    <!-- Or use CDN: Pico CSS / Tailwind -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
    <header>
        <nav>
            <ul>
                <li><a href="/">📊 Sessions</a></li>
                <li><a href="/stats">📈 Stats</a></li>
                <li><a href="/docs">📖 Docs</a></li>
            </ul>
            <ul>
                <li><span id="version">v0.1.0</span></li>
                <li><button id="dark-toggle">🌙</button></li>
            </ul>
        </nav>
    </header>
    <main>
        {% block content %}{% endblock %}
    </main>
    <footer>
        <small>MCP Debugger • MIT License • <a href="https://github.com/yourusername/mcp-debugger">GitHub</a></small>
    </footer>
    <!-- JavaScript -->
    <script src="/static/app.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
2. Session List Template (templates/sessions.html)
Purpose: Display sessions with search, filter, and pagination.

Key Sections:

Header Row:

Title: "Sessions"

"Record New Session" button → shows modal with proxy command.

Search & Filter Bar:

Search input: filter by name or server command (client-side or server-side).

Status filter dropdown: All, Running, Completed, Error.

"Clear Filters" button.

Session Table:

Columns: ID, Name, Server, Started, Duration, Messages, Status, Actions.

Status badges with colours.

Clicking a row → navigate to session detail.

Actions: 👁️ View (link), 📤 Export, 🗑️ Delete (with confirmation).

Pagination:

"Previous" / "Next" buttons.

Page number display: "Page 1 of 5".

Items per page selector: 25, 50, 100.

Empty State:

If no sessions: "No sessions recorded yet. Run mcp-debugger proxy to get started."

Show proxy command in a code block.

Example Table Row:

text
┌────┬────────────┬──────────────────────────┬─────────────────────┬─────────┬──────────┬───────────┬────────┐
│ ID │ Name │ Server │ Started │ Duration│ Messages │ Status │ Actions│
├────┼────────────┼──────────────────────────┼─────────────────────┼─────────┼──────────┼───────────┼────────┤
│ 42 │ filesystem │ npx -y .../filesystem... │ 2025-06-10 14:23:01 │ 2m 34s │ 142 │ 🟢 Completed│ 👁️ 📤 🗑️│
└────┴────────────┴──────────────────────────┴─────────────────────┴─────────┴──────────┴───────────┴────────┘ 3. API Endpoints (Enhanced)
Endpoint Method Query Params Description
/api/sessions GET page=1, limit=25, search=, status=, sort= Returns paginated sessions list with total count
/api/sessions/stats GET None Returns global stats (total, running, completed, error)
Response for /api/sessions?page=1&limit=25:

json
{
"data": [
{
"id": 42,
"friendly_name": "filesystem-test",
"server_command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
"server_command_truncated": "npx -y .../server-filesystem /tmp",
"started_at": "2025-06-10T14:23:01",
"ended_at": "2025-06-10T14:25:35",
"duration_seconds": 154,
"duration_human": "2m 34s",
"status": "completed",
"message_count": 142,
"error_count": 2
}
],
"pagination": {
"page": 1,
"limit": 25,
"total": 156,
"pages": 7
}
} 4. Frontend JavaScript (static/app.js)
Functions:

loadSessions() – Fetch sessions from API and render table.

renderTable(data) – Build table rows from session data.

applyFilters() – Get search/status filters and reload.

updatePagination(pagination) – Update page controls.

confirmDelete(id, name) – Show confirmation modal, then delete.

copyCommand() – Copy proxy command to clipboard.

Event Listeners:

Search input: input → debounced applyFilters().

Status dropdown: change → applyFilters().

Pagination buttons: click → loadSessions(page).

5. Static CSS (static/style.css)
   Keep it simple. Use Pico CSS or Tailwind CDN for most styling. Add custom styles for:

Status badges (green, yellow, red).

Table row hover effect.

Modal overlay for delete confirmation.

Responsive design (table scrollable on mobile).

🔗 Integration with Previous Days
Day 3 (Database): New helper methods in Database class:

get_sessions_paginated(page, limit, search, status) – returns sessions + total count.

get_session_stats() – returns total, running, completed, error counts.

Day 5 (List): The web session list should show the same data as CLI list command.

Day 20 (Config): The web UI should respect config (e.g., default_output).

⚙️ Production Considerations
Performance
Use COUNT(\*) for total count (indexed query).

Use LIMIT and OFFSET for pagination.

Truncate server command to 60 characters (show full on hover).

Cache session stats for 5 seconds (optional).

UX Considerations
Show loading spinner while fetching data.

Debounce search input (300ms) to avoid excessive API calls.

Auto-refresh every 10 seconds if there are running sessions (polling).

On "Record New Session" click, show modal with the mcp-debugger proxy command.

Security (Local Only)
No authentication required (listens on localhost only).

CORS: Allow only http://localhost:8000 origin.

Error Handling
If API fails, show error message with "Retry" button.

If database is missing, show "No sessions found. Run mcp-debugger proxy first."

✅ Day 27 Verification Checklist

# Check How to verify

1 Base template exists (templates/base.html) File present.
2 Session list template exists (templates/sessions.html) File present.
3 Home page loads with mcp-debugger web Open http://localhost:8000/ – page renders.
4 Sessions are displayed in a table After running proxy, sessions appear in table.
5 Status badges show correct colours 🟢 Completed, 🟡 Running, 🔴 Error.
6 Server command is truncated Long commands show "..." at end.
7 Duration is human-readable Shows "2m 34s" format.
8 Search box filters sessions Typing "filesystem" shows only matching sessions.
9 Status filter works Select "Running" – only running sessions.
10 Pagination works "Next" button shows next page.
11 Empty state shows helpful message Delete all sessions – shows proxy command.
12 "Record New Session" button Shows modal with mcp-debugger proxy command.
13 Click row navigates to session detail Click row → http://localhost:8000/session/1.
14 API endpoint with search/filter works curl http://localhost:8000/api/sessions?search=filesystem – filtered results.
15 ruff check passes No linting errors.
16 mypy --strict passes No type errors.
17 Documentation: update docs/web-ui.md Basic usage instructions.
18 Commit with message feat(web): add session list view with search and pagination –
💡 Tips for Day 27
Use Pico CSS or Tailwind CDN – don't build custom CSS from scratch. Focus on functionality.

Keep JavaScript simple – no framework required. Vanilla JS is fine.

Test with real sessions – run mcp-debugger proxy to create sessions, then view them in the web UI.

Pagination logic: Calculate offset = (page - 1) \* limit, send to API.

Search: Use SQL LIKE in the API: WHERE friendly_name LIKE '%search%' OR server_command LIKE '%search%'.

Auto-refresh: Only if there are running sessions – check status in the data.

🚀 After Day 27 – Next Day
Day 28: Session Detail View – Overview Panel – build the session detail page with metadata, stats cards, and tabs.

Day 28: Session Detail View – Overview Panel
You have a working session list (Day 27). Now it's time to build the session detail page – the heart of the Web UI where users can explore a single session in depth.

By the end of Day 28, users will be able to:

View a session's complete metadata (server, duration, status, etc.).

See summary statistics (total messages, tools, errors, latency).

Navigate between tabs: Overview, Messages, Tools, Errors, Replay.

Export the session in multiple formats.

Delete the session (with confirmation).

🎯 Core Objective
Build the session detail page (/session/{id}) with:

Component Description
Header Session ID, Name, Status badge, Server command
Overview Cards Duration, Messages, Tools, Errors, Avg Latency
Metadata Table Started, Ended, Protocol Version, Client Info, Server Info
Tab Navigation Overview, Messages, Tools, Errors, Replay
Action Buttons Export, Delete, Replay (opens replay interface)
📦 What You Need to Build
Component File Description
Session Detail Template templates/session_detail.html Main page with header, cards, tabs, and content
API Enhancement app.py Add /api/sessions/{id} endpoint with full metadata
Stats Calculation database.py Add get_session_stats(session_id) method
Static CSS static/style.css Card styles, tab styles, badge styles
Static JS static/app.js Tab switching, export actions, delete confirmation
🧠 Expected Behaviour

1. Session Header
   Purpose: Show key session information at a glance.

Content:

text
┌─────────────────────────────────────────────────────────────────────┐
│ Session #42 – "filesystem-test" 🟢 Completed │
│ Server: npx -y @modelcontextprotocol/server-filesystem /tmp │
│ Started: 2025-06-10 14:23:01 • Duration: 2m 34s │
└─────────────────────────────────────────────────────────────────────┘
Session ID and Name (large, bold).

Status badge (coloured).

Full server command (truncated with expand button).

Started at timestamp (local time).

Duration (human-readable).

Client/Server info (compact: "Client: test-client v1.0 • Server: filesystem v0.1").

2. Overview Cards
   Purpose: Show key statistics in a visual dashboard.

Cards (4 or 5):

Card Content Colour
📨 Messages Total messages (client→server / server→client) Blue
🔧 Tools Tools discovered / Tools called Green
❌ Errors Total errors / Error rate % Red (if >0)
⏱️ Avg Latency Average response time in ms Purple
💰 Cost Estimated cost (if tracking) Gold (optional)
Example:

text
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ 📨 Messages │ │ 🔧 Tools │ │ ❌ Errors │ │ ⏱️ Latency │
│ 142 total │ │ 8 / 45 │ │ 2 (1.4%) │ │ 23ms avg │
│ 71 → 71 ← │ │ calls │ │ │ │ │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
Card hover effect: Slight lift and shadow.

3. Metadata Section
   Purpose: Show detailed session metadata in a table.

Fields:

Field Description
Session ID Unique identifier
Name Friendly name (if provided)
Status Running / Completed / Error
Protocol Version MCP protocol version (e.g., "2025-03-26")
Started At Start timestamp (local time)
Ended At End timestamp (or "Still running")
Duration Human-readable duration
Server Command Full command (with copy button)
Client Info Name, Version (from initialize)
Server Info Name, Version (from initialize)
Capabilities Client/Server capabilities (expandable) 4. Tab Navigation
Purpose: Organise content into logical sections.

Tabs:

text
┌──────────────────────────────────────────────────────┐
│ [Overview] [Messages] [Tools] [Errors] [Replay] │
├──────────────────────────────────────────────────────┤
│ Content for the selected tab goes here │
│ │
└──────────────────────────────────────────────────────┘
Tab is highlighted when active.

Clicking a tab switches content (client-side, no page reload).

Replay tab: "Coming soon" or basic replay interface.

5. Action Buttons
   Purpose: Provide actions for the session.

Button Behaviour
📤 Export Opens dropdown: JSON, Markdown, OTLP
🔄 Replay Opens replay interface (Day 47+)
🗑️ Delete Shows confirmation modal, then deletes
📋 Copy ID Copies session ID to clipboard
🔗 API Endpoint: GET /api/sessions/{id}
Response Structure:

json
{
"session": {
"id": 42,
"friendly_name": "filesystem-test",
"server_command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
"started_at": "2025-06-10T14:23:01",
"ended_at": "2025-06-10T14:25:35",
"status": "completed",
"protocol_version": "2025-03-26",
"client_info": {"name": "test-client", "version": "1.0"},
"server_info": {"name": "filesystem", "version": "0.1"},
"capabilities": {"tools": {}}
},
"stats": {
"total_messages": 142,
"client_to_server": 71,
"server_to_client": 71,
"tools_discovered": 8,
"tools_called": 45,
"total_errors": 2,
"error_rate": 1.4,
"avg_latency_ms": 23.5,
"min_latency_ms": 5.0,
"max_latency_ms": 234.0
},
"tools": [
{"name": "read_file", "call_count": 45, "avg_latency_ms": 23.0}
],
"errors": [
{"type": "protocol", "message": "Method not found", "count": 2}
]
}
⚙️ Production Considerations
Performance
Fetch all data in one API call (avoid multiple round trips).

Cache stats for 5 seconds.

For large sessions (>10k messages), stats calculation may be slow – use indexed queries.

UX Considerations
Show loading spinner while fetching data.

If session doesn't exist, show 404 page with "Session not found".

Use skeleton loading for cards while data loads.

Error Handling
If API fails, show error message with "Retry" button.

If database is corrupted, show helpful error.

✅ Day 28 Verification Checklist

# Check How to verify

1 Session detail page loads http://localhost:8000/session/1 – page renders.
2 Session header shows correct data Name, status, server command, started, duration.
3 Overview cards show correct stats Messages, Tools, Errors, Latency match CLI stats command.
4 Metadata table shows all fields Protocol version, client/server info, capabilities.
5 Tabs switch correctly Click "Messages" – shows messages content.
6 Export button shows dropdown JSON, Markdown, OTLP options.
7 Delete button shows confirmation modal Click delete – modal appears.
8 Copy ID button works Copies to clipboard.
9 API endpoint returns full data curl /api/sessions/1 – JSON matches expected structure.
10 404 handling for non-existent session /session/9999 – shows "Session not found".
11 Loading state appears Slow connection shows spinner.
12 Error state handled API failure shows error with retry.
13 ruff check passes No linting errors.
14 mypy --strict passes No type errors.
15 Documentation updated docs/web-ui.md – session detail guide.
16 Commit with message feat(web): add session detail overview panel –
