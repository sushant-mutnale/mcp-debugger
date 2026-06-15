Day 17: CLI Replay Command – Exposing Replay to Users
You have the replay engine (Day 15) and diff visualisation (Day 16). Now it’s time to wrap them into a user‑friendly CLI command. Developers can now run:

bash
mcp-debugger replay <session_id> --server "new-server-command"
and see a detailed report of which responses changed, with colour‑coded diffs, summary statistics, and an exit code suitable for CI/CD.

By the end of Day 17, your tool will be able to regression‑test MCP servers – a game‑changer for anyone maintaining or upgrading MCP implementations.

🎯 Core Objective
Implement mcp-debugger replay command with the following features:

Feature	Behaviour
Replay a session	Load client messages from a recorded session, send them to a new server, compare responses.
Output formats	Rich terminal report (default) or JSON (--json) for scripting.
Diff display	Show only mismatched messages by default, with inline diffs. Use --verbose to show all messages.
Exit code	0 if all responses match (or only warnings), 1 if any mismatch or critical error.
Options	--server (required), --timeout, --max-messages, --filter-method, --json, --output, --verbose.
Persistence	Optionally save replay results to the database (--save) for later review.
Deliverables by end of day:

src/mcp_debugger/cli/replay_commands.py (or extend cli.py).

Integration with ReplayEngine and diff module.

Rich output: summary table, per‑message diff for mismatches.

Unit and integration tests.

Documentation updated.

🧠 Expected Behaviour
1. Command Signature
bash
mcp-debugger replay <session_id> --server <command> [OPTIONS]
Arguments:

session_id – ID of the recorded session to replay.

Options:

Option	Type	Default	Description
--server, -s	str	required	Command to launch the target server (e.g., npx -y @modelcontextprotocol/server-filesystem /tmp).
--timeout	int	5000	Timeout in milliseconds per request‑response pair.
--max-messages	int	None	Maximum number of client messages to replay (useful for testing a subset).
--filter-method	str	None	Only replay messages with this method name (e.g., --filter-method tools/call).
--verbose, -v	flag	False	Show all messages with diffs (even those that match). Default: only show mismatches.
--json	flag	False	Output raw JSON report (no Rich terminal formatting).
--output, -o	path	None	Write output to a file (instead of stdout). Works with both --json and terminal output.
--save	flag	False	Save replay results to the replays database table (for later querying).
--no-diff	flag	False	Skip detailed diff output (only show summary). Useful for quick checks.
2. Terminal Output (Default)
Summary section (Rich panel):

text
┌─────────────────────────────────────────────────────────────────┐
│ Replay of Session #42                                           │
│ Source server: npx -y .../server-filesystem /tmp                │
│ Target server: npx -y .../server-filesystem /tmp (new version)  │
│ Duration: 2.34 seconds                                          │
├─────────────────────────────────────────────────────────────────┤
│ Total messages replayed: 65                                     │
│ ✓ Successful matches: 62                                        │
│ ✗ Mismatches: 3                                                 │
│ ⏱ Timeouts: 0                                                   │
│ ❌ Errors: 0                                                     │
└─────────────────────────────────────────────────────────────────┘
Mismatch details (for each mismatched message):

text
Message #23: tools/call (client → server)
Tool: read_file
Arguments: {"path": "/tmp/test.txt"}

Original response:
  { "content": [{"type": "text", "text": "file content"}] }

Replayed response:
  { "content": [{"type": "text", "text": "different content"}] }

Differences:
  result.content[0].text
    - "file content"
    + "different content"
Use Rich panels, colour‑coding (red for removed, green for added, yellow for changed).

If --verbose: Show every message with a small indicator (✓ or ✗) and diff only if mismatched.

If --no-diff: Only show summary and list of mismatched message IDs (no inline diff).

3. JSON Output (--json)
Output a JSON object containing:

json
{
  "session_id": 42,
  "source_server_command": "...",
  "target_server_command": "...",
  "started_at": "2025-06-15T10:00:00Z",
  "ended_at": "2025-06-15T10:00:02.34Z",
  "duration_seconds": 2.34,
  "summary": {
    "total": 65,
    "matches": 62,
    "mismatches": 3,
    "timeouts": 0,
    "errors": 0
  },
  "messages": [
    {
      "original_message_id": 23,
      "method": "tools/call",
      "matched": false,
      "diff": [
        {
          "path": "result.content[0].text",
          "type": "changed",
          "old_value": "file content",
          "new_value": "different content"
        }
      ]
    }
  ]
}
This format is easy to parse in CI scripts.

4. Saving to Database (--save)
Create a new replays table (if not exists – Day 15 defined schema but not created).

Insert a row into replays with source session, target command, status, counts.

Insert rows into replay_messages for each replayed message.

Print a message: Replay saved as replay ID 5. Use 'mcp-debugger replay show 5' to view later. (Future enhancement: replay list and replay show commands, not required for MVP but leave room.)

For MVP, --save can be optional; implement it if time permits, otherwise postpone to Day 18.

5. Exit Code Logic
Condition	Exit Code
Replay completed successfully, all responses match	0
Replay completed, but some responses mismatched	1
Timeout or server crash	2
Invalid arguments (e.g., session not found)	1
This allows CI to fail when a server upgrade introduces breaking changes.

🔗 Integration with Previous Days
Day 15 (Replay Engine): ReplayEngine.replay() returns ReplayResult.

Day 16 (Diff): Each ReplayedMessage has diff and diff_text.

Day 3 (Database): If --save, insert into replays and replay_messages.

⚙️ Production Considerations
Performance
Replaying a large session (1000+ messages) may take minutes. Add a progress bar using rich.progress.Progress while replaying.

The --max-messages option allows users to test a subset.

Error Handling
If target server fails to start (command not found), print error and exit with code 2.

If server crashes during replay, print the message where it crashed and exit.

Progress Reporting
During replay, show a live progress bar:

text
Replaying session 42... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 45/65 (69%) • 0:00:23
Use rich.progress with Progress and BarColumn.

Interaction with --verbose
Default: Only show summary + mismatched messages.

--verbose: Show all messages (with ✓/✗ markers). For matches, show no diff; for mismatches, show diff.

Combining with --output
If --output file.txt and not --json, write the terminal output (including ANSI codes) to a file. Use console.save_text() or redirect manually.

If --output file.json and --json, write JSON.

✅ Day 17 Verification Checklist
#	Check	How to verify
1	mcp-debugger replay --help shows all options	Run command.
2	replay <id> --server <cmd> runs without errors	Use a session recorded from filesystem server, replay against same server → all matches.
3	Summary panel shows correct counts	Compare with manual counting.
4	Mismatched messages are displayed with inline diff	Modify the target server (e.g., change a response) → diff appears.
5	--verbose shows all messages	Output includes matched messages with ✓.
6	--json outputs valid JSON	Pipe to jq.
7	--output writes to file	File exists, content matches console output (or JSON).
8	--max-messages 10 replays only first 10 messages	Check summary count.
9	--filter-method tools/call replays only tool calls	No initialize or tools/list messages.
10	Exit code is 0 when all responses match	Run replay against identical server → echo $? = 0.
11	Exit code is 1 when mismatches exist	Modify server → exit code 1.
12	Exit code is 2 when server fails to start	--server "nonexistent" → exit code 2.
13	Progress bar appears during replay	Visual inspection.
14	Timeout handling: if server hangs, replay aborts and shows timeout error	Use --server "sleep 10 && cat" → timeout.
15	Unit tests for CLI command (mocked ReplayEngine)	pytest tests/test_cli.py::test_replay_command.
16	Integration test: record session → replay → verify match/mismatch detection	Extend Day 14 integration script.
17	mypy --strict passes	–
18	ruff check passes	–
19	Documentation updated (docs/commands.md with replay examples)	–
20	Commit with message feat(replay): add CLI replay command	–
