Day 22: Comprehensive Test Suite – Ensuring Rock‑Solid Reliability
You’ve built all the features and hardened performance (Day 21). Now you need confidence that every change won’t break existing functionality. A comprehensive test suite is the safety net that allows you to refactor, add features, and fix bugs without fear.

By the end of Day 22, mcp-debugger will have:

Unit tests for every module (target >90% coverage).

Integration tests for end‑to‑end workflows (proxy → DB → inspect → replay → export).

Property‑based tests using hypothesis to catch edge cases in message parsing and validation.

Stress tests that push the tool to its limits (10k messages, large payloads, concurrent sessions).

Coverage reporting in CI to prevent regression.

This transforms your codebase from “works for me” to “works for everyone”.

🎯 Core Objective
Build a comprehensive test suite across four layers:

Layer Purpose Tools
Unit tests Test individual functions/classes in isolation pytest, pytest-asyncio, mocking (unittest.mock or pytest-mock)
Integration tests Test end‑to‑end workflows with real (or mocked) servers pytest-asyncio, temporary DBs, real MCP servers (filesystem)
Property‑based tests Verify invariants (e.g., any valid MCP message round‑trips through models) hypothesis, hypothesis-jsonschema (for generating valid JSON‑RPC)
Stress tests Test performance and memory under load pytest-benchmark, memory-profiler, custom scripts
Deliverables by end of day:

pytest --cov shows >90% coverage across all modules.

All tests pass in CI (GitHub Actions) on every push.

A tests/ directory with well‑organized test files (mirroring src/ structure).

Documentation on how to run tests (docs/contributing.md).

🧠 Expected Behaviour

1. Test Organisation
   Mirror the src/ directory structure:

text
tests/
├── conftest.py # Shared fixtures (DB, temp dirs, mock servers)
├── test_cli/
│ ├── test_proxy.py
│ ├── test_list.py
│ ├── test_inspect.py
│ ├── test_validate.py
│ ├── test_stats.py
│ ├── test_export.py
│ └── test_replay.py
├── test_protocol/
│ ├── test_schemas.py
│ ├── test_validator.py
│ └── test_error_classifier.py
├── test_proxy/
│ └── test_stdio_proxy.py
├── test_storage/
│ └── test_database.py
├── test_replay/
│ ├── test_engine.py
│ └── test_diff.py
├── test_exporters/
│ ├── test_json.py
│ ├── test_markdown.py
│ └── test_otlp.py
├── test_config.py
├── test_integration.py # End‑to‑end workflows
├── test_stress.py # Performance benchmarks
└── test_property.py # Hypothesis‑based property tests 2. Unit Tests
Goal: >90% line coverage.

Mocking: Use pytest-mock to mock database, subprocess, file I/O, network calls (OTLP).

Parametrize: Use @pytest.mark.parametrize to test many inputs.

Example coverage targets:

Module Target Key areas
protocol/schemas.py 100% All Pydantic models, validators, helper functions.
protocol/validator.py 95% All validation rules (handshake, method names, schemas).
protocol/error_classifier.py 100% All error codes and categories.
storage/database.py 90% All CRUD methods, error handling, transactions.
proxy/stdio_proxy.py 85% Subprocess lifecycle, I/O forwarding, signal handling.
replay/engine.py 90% Replay loop, timeout handling, diff integration.
cli/\*.py 80% Command parsing, flag handling, output generation (hard to test fully).
config.py 95% Load/save/get/set, validation. 3. Integration Tests
Goal: Test the entire pipeline: proxy → inspect → stats → export → replay.

Approach: Use a temporary directory, a mock or real MCP server (filesystem), and a test‑specific database.

Test sequence:

Start proxy with a mock server that responds to initialize, tools/list, and a few tools/call.
Send a predefined sequence of messages via stdin.
Stop proxy, verify DB contains correct session, messages, tools.
Run inspect on the session (compare output snapshot or query DB).
Run stats and verify aggregate counts.
Run export to JSON and validate structure.
Run replay against the same server and verify 100% match.
Run replay against a different server (or a modified version) and verify mismatches are detected.
Tools: subprocess or asyncio.create_subprocess_exec to run the CLI commands as a child process, or call the internal functions directly (more stable).

4. Property‑Based Tests (Hypothesis)
   Goal: Verify invariants that should hold for all valid inputs.

Examples:

Any valid JSON‑RPC request parsed by schemas.JSONRPCRequest can be serialized back to JSON and re‑parsed identically.

ProtocolValidator.validate_message() never raises an exception; always returns a list of ValidationResult.

Database.log_message() and Database.get_messages() are consistent (inserted message can be retrieved).

compare_json() is symmetric: compare(a, b) == compare(b, a) (ignoring order).

Strategy: Use hypothesis strategies to generate valid JSON‑RPC messages (based on MCP spec) and arbitrary JSON values. Then run tests on thousands of random inputs.

5. Stress Tests
   Goal: Ensure the tool handles realistic workloads without memory leaks or timeout.

Scenarios:

Large session: Generate 10,000 messages (random method, params, latency) and insert into DB via proxy. Measure time (< 2 seconds? < 5? acceptable).

Large replay: Replay that session against a mock server that responds instantly. Measure time.

Concurrent proxies: Run two proxies simultaneously against different servers (or same server but different sessions) – no database corruption.

Large messages: Send a 50MB JSON message; ensure proxy doesn't crash (may be slow, but should not explode).

Tools: pytest-benchmark for timing, memory-profiler for memory tracking, pytest-xdist for concurrent test runs.

🔗 Integration with Previous Days
All modules: Tests will validate every feature built.

Day 7 (Doctor): Test doctor command output.

Day 20 (Config): Test config loading and fallback.

Day 21 (Performance): Stress tests will verify performance improvements are real.

⚙️ Production Considerations
Running Tests in CI
GitHub Actions: run pytest on Python 3.11 and 3.12 on every push.

Use pytest-cov to generate coverage reports and fail if coverage drops below threshold (e.g., 85%).

Integration tests that require npx should be run only if Node.js is installed (check in CI).

Managing Test Data
Use temporary directories (tmp_path fixture in pytest) for databases and mock server scripts.

Avoid hardcoded paths.

Use environment variables to control OTLP export in tests (mocked or skipped).

Mocking Strategies
For asyncio.subprocess, use pytest-asyncio and mock create_subprocess_exec to return a mock process.

For aiosqlite, use an in‑memory database (:memory:) for speed in unit tests (but not for integration tests where persistence is needed).

For OTLP exporter, mock the gRPC client to avoid network calls.

Coverage Reporting
pytest --cov=src/mcp_debugger --cov-report=html --cov-report=term

Coverage should be measured excluding test files and CLI entry points (**main**.py).

Aim for >90% overall, but individual modules may have lower coverage (e.g., CLI due to Typer magic). Still try.

✅ Day 22 Verification Checklist

# Check How to verify

1 tests/ directory mirrors src/ structure Files exist for each module.
2 All existing tests pass (pytest) pytest – green.
3 Coverage report generated (pytest --cov) Shows coverage >85% (or target).
4 Unit tests for schemas.py cover all models and validators test_protocol.py includes parametrized tests.
5 Unit tests for validator.py cover all rules Each rule has a test (valid and invalid).
6 Unit tests for database.py cover all methods with error handling Mock DB or real DB with rollbacks.
7 Unit tests for stdio_proxy.py mock subprocess to test I/O forwarding Mock process with asyncio.create_subprocess_exec.
8 Unit tests for replay_engine.py mock server responses Verify replay sends messages and captures responses.
9 Integration test runs full pipeline (proxy → inspect → stats → export → replay) Test passes in CI.
10 Property‑based tests for schemas (round‑trip) hypothesis tests pass with 100+ random examples.
11 Property‑based tests for compare_json (symmetry, idempotence) Pass.
12 Stress test: 10k messages inserted in < 5 seconds pytest-benchmark shows acceptable time.
13 Stress test: replay 10k messages in < 10 seconds Acceptable.
14 Stress test: large message (50MB) does not crash proxy Handles with warning.
15 mypy --strict passes in test files (optional, but nice) –
16 ruff check passes on test files –
17 Documentation: docs/contributing.md with test instructions Created.
18 CI runs all tests on every push and PR GitHub Actions green.
19 Commit with message test: comprehensive test suite –
