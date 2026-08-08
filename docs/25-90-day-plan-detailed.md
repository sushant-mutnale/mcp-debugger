---

## 3. Technology Stack (Extended)

| Layer | Technology | Justification |
|-------|------------|---------------|
| **Language** | Python 3.11+ | Native asyncio, strong stdlib, user's expertise |
| **CLI** | Typer + Rich | Type-hinted commands, beautiful output |
| **Web Backend** | FastAPI + Jinja2 | Python-native, easy to extend, no frontend expertise needed |
| **Frontend** | React + AgentPrism (MIT) | Reuse proven visualization; focus on data pipeline |
| **Database** | SQLite + (optional: Postgres) | Local-first, zero config; Postgres for team features |
| **Async** | asyncio + anyio | Non-blocking I/O for proxies and replay |
| **Data Validation** | Pydantic v2 | Robust, fast, industry standard |
| **Testing** | pytest + pytest-asyncio + Playwright | Full stack testing |
| **Packaging** | uv | Modern, fast, replaces pip/poetry |
| **CI/CD** | GitHub Actions | Native integration |

---

## 4. The 90-Day Build Plan

### PHASE 2: WEB UI + SSE/HTTP PROXY + ADVANCED REPLAY (Days 26–55)

#### Week 4: Web UI Foundation (Days 26–32)

**Day 26 – FastAPI Backend Setup**

- Add FastAPI, Jinja2, uvicorn dependencies.
- Create `src/mcp_debugger/web/` structure.
- Implement FastAPI app with routes: `/`, `/api/sessions`, `/session/{id}`.
- Add basic Jinja2 templates.
- **Verification:** `uv run uvicorn ...` starts; `/api/sessions` returns JSON.

**Day 27 – Session List View**

- Create `base.html` and `sessions.html`.
- Display sessions table with status badges.
- Add search/filter and pagination.
- **Verification:** `/` shows styled session list with data from SQLite.

**Day 28 – Session Detail – Overview**

- Add `session_detail.html` with overview cards, tabs (Overview, Messages, Tools, Errors, Replay).
- Show metadata, stats, export/delete buttons.
- **Verification:** `/session/1` shows complete overview.

**Day 29 – Session Detail – Message Viewer**

- Implement message list with direction indicators, method colors, expandable JSON.
- Add filtering and search.
- **Verification:** messages render, filters work, JSON is syntax-highlighted.

**Day 30 – Tools & Errors Views**

- Create tools tab with schema and usage; errors tab with classification and suggestions.
- **Verification:** tools and errors appear correctly.

**Day 31 – Web UI Polish**

- Add loading states, WebSocket for live updates, session comparison page.
- Improve responsiveness and dark mode.
- **Verification:** live updates work; comparison page shows diffs.

**Day 32 – Week 4 Integration**

- Write integration tests, add `mcp-debugger web` command, test with real MCP sessions.
- **Verification:** all tests pass; `web` command opens browser.

---

#### Week 5: Interactive Inspector & Advanced Views (Days 33–39)

**Day 33 – Timeline Visualization**

- Add timeline chart (Chart.js) showing messages over time with zoom/pan.
- **Verification:** timeline renders; hover shows details; click jumps to message.

**Day 34 – Message Detail View**

- Create message detail page showing request/response pair, latency, raw JSON.
- Add navigation and "Replay from here".
- **Verification:** message detail works and navigation is smooth.

**Day 35 – Search & Advanced Filtering**

- Implement full‑text search across sessions, saved searches, advanced filters (date, server, tool).
- **Verification:** search results appear <1s; filters combine correctly.

**Day 36 – Statistics Dashboard**

- Build global stats page (charts for usage, errors, latency).
- Add per‑session analytics and PDF export.
- **Verification:** stats match SQLite data; charts render.

**Day 37 – Live Proxy Session View**

- Show live messages via WebSocket; add follow mode and real‑time stats.
- **Verification:** running proxy with `--web` shows live updates.

**Day 38 – AgentPrism Integration**

- Study AgentPrism and add adapter for MCP messages; display agent decision trees.
- **Verification:** AgentPrism components render correctly.

**Day 39 – UI Polish & Dark Mode**

- Finalize dark mode, keyboard shortcuts, shareable URLs, E2E tests with Playwright.
- **Verification:** dark mode works; shortcuts responsive; E2E tests pass.

---

#### Week 6: SSE/HTTP Proxy (Days 40–46)

**Day 40 – HTTP Proxy Foundation**

- Create `http_proxy.py`; support GET/POST and SSE streams; add `--transport` flag.
- **Verification:** HTTP proxy logs requests/responses.

**Day 41 – SSE Proxy Implementation**

- Parse SSE events, log to SQLite, handle reconnection.
- **Verification:** SSE events appear in DB.

**Day 42 – WebSocket Support**

- Implement WebSocket proxy (binary/text), log messages, handle close.
- **Verification:** WebSocket messages are logged.

**Day 43 – Transport Abstraction**

- Unified interface for stdio, HTTP, WebSocket; auto‑detection.
- **Verification:** all transports work; auto‑detect picks correct one.

**Day 44 – Bidirectional Message Routing**

- Implement router for all transports; support filtering/injection.
- **Verification:** messages route correctly; injection works.

**Day 45 – Web UI for HTTP/SSE**

- Update Web UI to show HTTP/SSE sessions with connection status and real‑time events.
- **Verification:** UI displays HTTP/SSE session details.

**Day 46 – Week 6 Integration**

- Write tests for all proxies, test with real HTTP/SSE servers, document.
- **Verification:** all tests pass; docs updated.

---

#### Week 7: Replay Engine v2 (Days 47–53)

**Day 47 – Interactive Replay Foundation**

- Add `--interactive` flag to replay; step through messages; allow modification.
- **Verification:** interactive replay works with `rich.prompt`.

**Day 48 – Parameter Modification**

- Support modification via file (`--modify`) and interactive edit; store modification history.
- **Verification:** modified parameters produce new responses.

**Day 49 – Replay Performance**

- Add `--speed` (real-time, fast, instant); concurrent replay; progress bar.
- **Verification:** speeds work; concurrent replay is stable.

**Day 50 – Replay Diff Improvements**

- Semantic, structural, value diff; color‑coded output; web UI diff viewer.
- **Verification:** diffs are accurate and readable.

**Day 51 – Regression Testing Framework**

- Add `mcp-debugger regression` command; baseline management; CI exit codes.
- **Verification:** regression command passes/fails based on diffs.

**Day 52 – Web UI for Replay**

- Replay interface in web UI; show progress, diff, controls.
- **Verification:** replay runs from UI; results displayed.

**Day 53 – Week 7 Integration**

- Comprehensive tests, performance benchmarks, docs.
- **Verification:** all tests pass; docs complete.

---

#### Week 8: Polish & Integration (Days 54–55)

**Day 54 – Comprehensive Testing**

- Achieve >80% test coverage; add security, load, stress tests.
- **Verification:** coverage >80%; all tests pass.

**Day 55 – Documentation & Release**

- Update README, write Web UI/Replay docs, create demo media, tag v0.2.0, publish to PyPI.
- **Verification:** docs complete; PyPI release successful.

---

### PHASE 3: MULTI‑FRAMEWORK AGENT TRACING + TIME‑TRAVEL + TEAM (Days 56–90)

#### Week 9: Agent SDK Foundation (Days 56–62)

**Day 56 – Agent Tracing Architecture**

- Define `AgentTrace`, `AgentStep` models; design storage schema; plan OpenTelemetry integration.
- **Verification:** models defined; schema created.

**Day 57 – `@trace_agent` Decorator**

- Implement decorator capturing input/output, LLM/tool calls; support sync/async.
- **Verification:** decorated functions produce traces in SQLite.

**Day 58 – LangChain Adapter**

- Create `LangChainTracer` and callback handler; capture LLM/tool/chain events.
- **Verification:** traces from LangChain apps appear.

**Day 59 – LangChain Integration Testing**

- Write tests with real LangChain examples; benchmark overhead (<5%).
- **Verification:** tests pass; overhead acceptable.

**Day 60 – Agent Trace Storage**

- Implement storage, retrieval, search, compression, retention.
- **Verification:** CRUD operations work; search is fast.

**Day 61 – Agent Trace Visualization (Web UI)**

- Build tree/timeline view for agent traces; show cost/tokens/errors.
- **Verification:** traces are displayed correctly.

**Day 62 – Week 9 Integration**

- Full end‑to‑end tests; docs for agent tracing.
- **Verification:** all tests pass; docs complete.

---

#### Week 10: OpenAI Agents + MCP-Agent Adapters (Days 63–69)

**Day 63 – OpenAI Agents SDK Adapter**

- Implement `OpenAIAgentTracer`; capture agent runs, tool calls, handoffs, tokens.
- **Verification:** traces from OpenAI Agents SDK appear.

**Day 64 – OpenAI Agents Integration Testing**

- Test with real examples; benchmark overhead.
- **Verification:** tests pass; overhead <5%.

**Day 65 – MCP-Agent Adapter**

- Use existing MCP proxy to trace agent decisions; correlate MCP calls with agent steps.
- **Verification:** traces from MCP-Agent work.

**Day 66 – Multi‑Framework Trace Aggregation**

- Merge traces from different frameworks into unified view.
- **Verification:** aggregated trace shows all steps.

**Day 67 – Framework Detection & Auto‑Configuration**

- Auto‑detect frameworks; generate config; support environment variables.
- **Verification:** detection works; config generated.

**Day 68 – Web UI for Multi‑Framework Traces**

- Framework selector; show framework‑specific details; cross‑framework comparison.
- **Verification:** UI displays multiple framework traces correctly.

**Day 69 – Week 10 Integration**

- Comprehensive tests; docs for adapters.
- **Verification:** all tests pass; docs complete.

---

#### Week 11: Time‑Travel Replay (Days 70–76)

**Day 70 – State Capture Architecture**

- Design checkpoint system; serialization format; storage in SQLite.
- **Verification:** architecture documented; serialization works.

**Day 71 – State Capture Implementation**

- Add capture hooks; create checkpoints at each step; manage checkpoints.
- **Verification:** checkpoints are stored and retrievable.

**Day 72 – Time‑Travel Replay Implementation**

- Implement replay from checkpoint; add CLI command `agent replay` with `--from/--to`.
- **Verification:** replay from checkpoint works.

**Day 73 – Time‑Travel Web UI**

- Show checkpoint timeline; navigate and replay from UI; side‑by‑side comparison.
- **Verification:** UI allows time‑travel.

**Day 74 – Agent Comparison & Diff**

- Compare two runs; show diff in tree/timeline/cost; CLI `agent compare`.
- **Verification:** comparison works; diff is clear.

**Day 75 – Performance Optimization**

- Incremental checkpoints, compression, caching; benchmark improvements.
- **Verification:** storage reduced; replay faster.

**Day 76 – Week 11 Integration**

- Tests, benchmarks, docs for time‑travel.
- **Verification:** all tests pass; docs complete.

---

#### Week 12: Team Features (Days 77–83)

**Day 77 – Cloud Sync Foundation**

- Design sync protocol; implement local sync queue; authentication; encryption.
- **Verification:** sync works locally; auth/encryption functional.

**Day 78 – Team Sharing & Collaboration**

- Share sessions; add comments, tags; CLI `share`; Web UI comment system.
- **Verification:** sharing and comments work.

**Day 79 – CI/CD Integration**

- GitHub Action, GitLab CI; `ci` command with JUnit XML; regression in CI.
- **Verification:** CI jobs run successfully.

**Day 80 – Team Dashboard**

- Team sessions, stats, activity feed; RBAC; audit logging; invitations.
- **Verification:** dashboard functional; permissions enforced.

**Day 81 – Enterprise Features**

- SSO, advanced RBAC, compliance reporting, self‑hosted Helm charts.
- **Verification:** SSO works; self‑hosted deployment works.

**Day 82 – API & SDK**

- Public REST API; Python SDK; OpenAPI docs; rate limiting.
- **Verification:** API and SDK work; docs generated.

**Day 83 – Week 12 Integration**

- Comprehensive tests; docs for team/enterprise features.
- **Verification:** all tests pass; docs complete.

---

#### Week 13: Polish, Documentation & Launch (Days 84–90)

**Day 84 – Comprehensive Testing**

- Achieve >85% test coverage; security, performance, load, fuzzing tests.
- **Verification:** coverage >85%; all tests pass.

**Day 85 – Performance Optimization**

- Profile and optimize hot paths; add caching; improve SQLite/JSON handling.
- **Verification:** performance targets met.

**Day 86 – Documentation Complete**

- User guide, API reference, deployment, troubleshooting, FAQ; add diagrams and video.
- **Verification:** all docs complete and reviewed.

**Day 87 – Marketing & Community**

- Create launch content (blog, social, demo video); update GitHub repo (templates, contributing guide).
- **Verification:** content ready; repo polished.

**Day 88 – Release Preparation**

- Update CHANGELOG; bump version to v1.0.0; build wheels; test install; create release notes.
- **Verification:** release artifacts ready.

**Day 89 – Launch Day**

- Publish to PyPI; release on GitHub; publish launch content; monitor feedback.
- **Verification:** release successful; feedback collected.

**Day 90 – Post‑Launch & Planning**

- Review metrics; prioritize issues; plan v1.1; write retrospective.
- **Verification:** metrics tracked; roadmap drafted; retrospective done.

---

## 5. Summary: What You'll Have After 90 Days

| Phase                    | Features                                                       | Status      |
| ------------------------ | -------------------------------------------------------------- | ----------- |
| **Phase 1** (Days 1-25)  | CLI, SQLite, stdio proxy, validate, replay, export             | ✅ DONE     |
| **Phase 2** (Days 26-55) | Web UI, HTTP/SSE proxy, interactive replay, regression testing | 🔨 BUILDING |
| **Phase 3** (Days 56-90) | Agent tracing, time-travel, team features, CI/CD               | 📅 PLANNED  |

---

## 6. Monetization Path

| Tier            | Features                                           | Price     |
| --------------- | -------------------------------------------------- | --------- |
| **Open Source** | CLI, SQLite, stdio/HTTP proxy, basic replay        | Free      |
| **Pro**         | Web UI, advanced replay, OTLP export, all adapters | $29/month |
| **Team**        | Shared sessions, comments, RBAC, audit logs        | $99/month |
| **Enterprise**  | SSO, self-hosted, compliance, support              | Contact   |

---

## 7. Success Metrics

| Metric                   | Target    |
| ------------------------ | --------- |
| GitHub Stars             | 5,000+    |
| Weekly Downloads         | 100,000+  |
| Active Users             | 10,000+   |
| Open Source Contributors | 50+       |
| Revenue (Year 1)         | $100,000+ |

---

## 8. Final Thoughts

You now have a complete 90-day plan to build a category-defining tool for MCP and AI agent debugging. The key to success is:

1. **Focus on solving real pain** — MCP debugging is currently done with print statements
2. **Ship early and often** — Each week should end with working software
3. **Listen to users** — The community will tell you what to build next
4. **Stay local-first** — This is your competitive advantage
5. **Build in public** — Share progress on social media

Good luck! You're building something that the developer community desperately needs.

---

**End of Document**
