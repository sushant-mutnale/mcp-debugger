/**
 * MCP Debugger Web UI – Session detail page logic
 * Handles: fetch session data, render cards, tabs, metadata, export, delete
 */

(function () {
  "use strict";

  // Session ID is injected by Jinja2 into a data attribute
  const rootEl = document.getElementById("session-root");
  const SESSION_ID = rootEl ? parseInt(rootEl.dataset.sessionId, 10) : null;

  // ── DOM refs ─────────────────────────────────────────────────
  const headerName     = document.getElementById("headerName");
  const headerStatus   = document.getElementById("headerStatus");
  const headerServer   = document.getElementById("headerServer");
  const headerMeta     = document.getElementById("headerMeta");
  const cardMessages   = document.getElementById("cardMessages");
  const cardMessagesSub = document.getElementById("cardMessagesSub");
  const cardTools      = document.getElementById("cardTools");
  const cardToolsSub   = document.getElementById("cardToolsSub");
  const cardErrors     = document.getElementById("cardErrors");
  const cardErrorsSub  = document.getElementById("cardErrorsSub");
  const cardLatency    = document.getElementById("cardLatency");
  const cardLatencySub = document.getElementById("cardLatencySub");
  const metaTable      = document.getElementById("metaTable");
  const tabBtns        = document.querySelectorAll(".tab-btn");
  const tabPanels      = document.querySelectorAll(".tab-panel");
  const toolsList      = document.getElementById("toolsList");
  const errorsList     = document.getElementById("errorsList");
  const deleteBtn      = document.getElementById("deleteBtn");
  const deleteModal    = document.getElementById("deleteModal");
  const confirmDeleteBtn = document.getElementById("confirmDeleteBtn");
  const cancelDeleteBtn  = document.getElementById("cancelDeleteBtn");
  const copyIdBtn      = document.getElementById("copyIdBtn");
  const loadingEl      = document.getElementById("detailLoading");
  const contentEl      = document.getElementById("detailContent");
  const errorEl        = document.getElementById("detailError");
  const retryBtn       = document.getElementById("retryBtn");

  // ── Helpers ───────────────────────────────────────────────────
  function escHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function formatDate(dateStr) {
    if (!dateStr) return "—";
    const d = new Date(dateStr.endsWith("Z") ? dateStr : dateStr + "Z");
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  }

  function formatDuration(secs) {
    if (secs == null) return "—";
    if (secs < 60) return `${secs}s`;
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s}s`;
  }

  function statusBadge(status) {
    const map = {
      completed: ["badge-completed", "✓ Completed"],
      running:   ["badge-running",   "● Running"],
      error:     ["badge-error",     "✗ Error"],
    };
    const [cls, label] = map[status] ?? ["badge-unknown", "? Unknown"];
    return `<span class="badge ${cls}">${label}</span>`;
  }

  // ── Tab switching ─────────────────────────────────────────────
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      tabBtns.forEach((b) => b.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.add("hidden"));
      btn.classList.add("active");
      const panel = document.getElementById(`tab-${target}`);
      if (panel) panel.classList.remove("hidden");
    });
  });

  // ── Render helpers ─────────────────────────────────────────────
  function renderHeader(session) {
    const name = session.friendly_name || `Session #${session.id}`;
    if (headerName) headerName.textContent = name;
    if (headerStatus) headerStatus.innerHTML = statusBadge(session.status);
    if (headerServer) {
      headerServer.textContent = session.server_command || "—";
      headerServer.title = session.server_command || "";
    }
    if (headerMeta) {
      const dur = session.duration_seconds != null
        ? formatDuration(session.duration_seconds) : "—";
      headerMeta.textContent =
        `Started ${formatDate(session.started_at)} • Duration: ${dur}`;
    }
    if (copyIdBtn) {
      copyIdBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(String(session.id)).catch(() => {});
        copyIdBtn.textContent = "✓ Copied!";
        setTimeout(() => { copyIdBtn.textContent = "📋 Copy ID"; }, 2000);
      });
    }
  }

  function renderCards(stats) {
    if (cardMessages) cardMessages.textContent = stats.total_messages ?? "—";
    if (cardMessagesSub) {
      cardMessagesSub.textContent =
        `↑ ${stats.client_to_server ?? 0} client  ↓ ${stats.server_to_client ?? 0} server`;
    }
    if (cardTools) cardTools.textContent =
      `${stats.tools_discovered ?? 0} / ${stats.tools_called ?? 0}`;
    if (cardToolsSub) cardToolsSub.textContent = "discovered / called";

    if (cardErrors) cardErrors.textContent = stats.total_errors ?? 0;
    if (cardErrorsSub) {
      const rate = stats.error_rate ?? 0;
      cardErrorsSub.textContent = rate > 0 ? `${rate}% error rate` : "No errors";
      if (stats.total_errors > 0 && cardErrors) {
        cardErrors.classList.add("text-red-400");
      }
    }
    if (cardLatency) {
      cardLatency.textContent =
        stats.avg_latency_ms != null ? `${stats.avg_latency_ms}ms` : "—";
    }
    if (cardLatencySub) {
      cardLatencySub.textContent =
        (stats.min_latency_ms != null && stats.max_latency_ms != null)
          ? `min ${stats.min_latency_ms}ms / max ${stats.max_latency_ms}ms`
          : "No latency data";
    }
  }

  function renderMetadata(session) {
    if (!metaTable) return;
    const rows = [
      ["Session ID", session.id],
      ["Friendly Name", session.friendly_name || "—"],
      ["Status", statusBadge(session.status)],
      ["Protocol Version", session.protocol_version || "—"],
      ["Started At", formatDate(session.started_at)],
      ["Ended At", session.ended_at ? formatDate(session.ended_at) : "Still running"],
      ["Duration", formatDuration(session.duration_seconds)],
      ["Server Command", `<code class="code-block text-xs">${escHtml(session.server_command || "—")}</code>`],
    ];
    metaTable.innerHTML = rows.map(([label, value]) => `
      <tr class="border-b border-[#292e42]">
        <td class="py-3 pr-6 text-xs text-gray-500 uppercase tracking-wider font-semibold whitespace-nowrap">${label}</td>
        <td class="py-3 text-sm text-gray-200">${value}</td>
      </tr>
    `).join("");
  }

  function renderTools(tools) {
    if (!toolsList) return;
    if (!tools || tools.length === 0) {
      toolsList.innerHTML = `<p class="text-gray-500 text-sm">No tools discovered in this session.</p>`;
      return;
    }
    toolsList.innerHTML = tools.map((t) => `
      <div class="bg-[#1f2335] border border-[#292e42] rounded-lg p-4 flex justify-between items-start">
        <div>
          <div class="font-mono text-sm text-[#7aa2f7] font-semibold">${escHtml(t.name)}</div>
          <div class="text-xs text-gray-500 mt-1">${escHtml(t.description || "No description")}</div>
        </div>
        <div class="text-xs text-gray-400 ml-4 text-right">
          <div>${t.call_count ?? 0} calls</div>
        </div>
      </div>
    `).join("");
  }

  function renderErrors(errors) {
    if (!errorsList) return;
    if (!errors || errors.length === 0) {
      errorsList.innerHTML = `<p class="text-gray-500 text-sm">No errors recorded in this session. 🎉</p>`;
      return;
    }
    errorsList.innerHTML = errors.map((e) => `
      <div class="bg-[#1f2335] border border-red-900/40 rounded-lg p-4">
        <div class="flex items-center gap-2 mb-1">
          <span class="badge badge-error">${escHtml(e.error_type || "error")}</span>
          <span class="text-xs text-gray-400">${formatDate(e.classified_at)}</span>
        </div>
        <div class="text-sm text-red-300 font-mono mt-1">${escHtml(e.message || "")}</div>
      </div>
    `).join("");
  }

  // ── Delete ────────────────────────────────────────────────────
  if (deleteBtn && deleteModal) {
    deleteBtn.addEventListener("click", () => deleteModal.classList.remove("hidden"));
  }
  if (cancelDeleteBtn) {
    cancelDeleteBtn.addEventListener("click", () => deleteModal.classList.add("hidden"));
  }
  if (confirmDeleteBtn && SESSION_ID) {
    confirmDeleteBtn.addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/sessions/${SESSION_ID}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          window.location.href = "/";
        } else {
          alert("Delete failed. Please try again.");
        }
      } catch {
        alert("Delete failed. Please try again.");
      }
    });
  }

  // ── Export dropdown ───────────────────────────────────────────
  const exportBtn = document.getElementById("exportBtn");
  const exportMenu = document.getElementById("exportMenu");
  if (exportBtn && exportMenu) {
    exportBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      exportMenu.classList.toggle("hidden");
    });
    document.addEventListener("click", () => exportMenu.classList.add("hidden"));
  }

  // ── Load ──────────────────────────────────────────────────────
  async function loadSession() {
    if (!SESSION_ID) return;
    if (loadingEl) loadingEl.classList.remove("hidden");
    if (contentEl) contentEl.classList.add("hidden");
    if (errorEl) errorEl.classList.add("hidden");

    try {
      const res = await fetch(`/api/sessions/${SESSION_ID}`);
      if (res.status === 404) {
        if (loadingEl) loadingEl.classList.add("hidden");
        if (errorEl) {
          errorEl.classList.remove("hidden");
          errorEl.querySelector("#errorMsg").textContent =
            `Session #${SESSION_ID} was not found.`;
        }
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      renderHeader(data.session);
      renderCards(data.stats || {});
      renderMetadata(data.session);
      renderTools(data.tools || []);
      renderErrors(data.errors || []);

      if (loadingEl) loadingEl.classList.add("hidden");
      if (contentEl) contentEl.classList.remove("hidden");
    } catch (err) {
      console.error("Failed to load session:", err);
      if (loadingEl) loadingEl.classList.add("hidden");
      if (errorEl) errorEl.classList.remove("hidden");
    }
  }

  if (retryBtn) retryBtn.addEventListener("click", loadSession);

  document.addEventListener("DOMContentLoaded", loadSession);
})();
