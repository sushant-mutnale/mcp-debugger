# Web UI

The `mcp-debugger` includes a built-in web interface for inspecting and managing your MCP debugging sessions. This provides a more visual and easier-to-navigate alternative to the CLI commands for complex sessions.

## Starting the Server

To launch the web interface, use the `web` command:

```bash
mcp-debugger web
```

By default, this will start a local server at `http://127.0.0.1:8000`.

### Options

- `--port`, `-p`: Change the port the server listens on (default: `8000`).
- `--host`, `-h`: Change the host interface to bind to (default: `127.0.0.1`). Use `0.0.0.0` to expose it on your local network (use with caution).
- `--open`: Automatically open the Web UI in your default web browser once the server starts.

Example:

```bash
mcp-debugger web --port 8080 --open
```

## Features

### Session List
The home page displays all recorded sessions, showing their IDs, names, commands, status, and message counts. You can use the filter box to quickly find a specific session by ID, name, or command.

### Session Details (Coming Soon)
Future updates will allow you to click into a session to see detailed insights, raw JSON-RPC messages, and full execution traces directly in the browser.

## API Endpoints

The Web UI is powered by a JSON API which you can also interact with directly if you want to build custom integrations or extract data programmatically.

- `GET /api/sessions`: Returns a list of all sessions.
  - Query Params: `limit` (default 25), `offset` (default 0), `status` (filter).
- `GET /api/sessions/{id}`: Returns detailed metadata about a specific session.
- `GET /api/sessions/{id}/messages`: Returns messages for a specific session.
  - Query Params: `method`, `direction`, `search`, `limit`, `offset`.

All endpoints return JSON responses.
