/**
 * MCP Debugger Web UI – Sessions list page logic
 * Handles: fetch, search, status filter, pagination, modal, delete
 */

(function () {
  "use strict";

  // ── State ─────────────────────────────────────────────────────
  let currentPage = 1;
  let currentSearch = "";
  let currentStatus = "";
  let currentLimit = 25;
  let totalPages = 1;
  let searchDebounce = null;

  // ── DOM refs ──────────────────────────────────────────────────
  const searchInput   = document.getElementById("searchInput");
  const statusFilter  = document.getElementById("statusFilter");
  const limitSelect   = document.getElementById("limitSelect");
  const refreshBtn    = document.getElementById("refreshBtn");
  const prevBtn       = document.getElementById("prevBtn");
  const nextBtn       = document.getElementById("nextBtn");
  const pageInfo      = document.getElementById("pageInfo");
  const totalInfo     = document.getElementById("totalInfo");
  const tbody         = document.getElementById("sessionsTbody");
  const loadingState  = document.getElementById("loadingState");
  const emptyState    = document.getElementById("emptyState");
  const tableContainer = document.getElementById("tableContainer");
  const newSessionBtn = document.getElementById("newSessionBtn");
  const modal         = document.getElementById("newSessionModal");
  const closeModalBtn = document.getElementById("closeModalBtn");
  const deleteModal   = document.getElementById("deleteModal");
  const deleteName    = document.getElementById("deleteName");
  const confirmDeleteBtn = document.getElementById("confirmDeleteBtn");
  const cancelDeleteBtn  = document.getElementById("cancelDeleteBtn");

  let pendingDeleteId = null;

  // ── Helpers ───────────────────────────────────────────────────
  function formatDate(dateStr) {
    if (!dateStr) return "—";
    const d = new Date(dateStr.endsWith("Z") ? dateStr : dateStr + "Z");
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
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

  function truncate(str, n) {
    if (!str) return "—";
    return str.length > n ? str.slice(0, n - 3) + "…" : str;
  }

  // ── Display state switches ────────────────────────────────────
  function showLoading() {
    loadingState.classList.remove("hidden");
    emptyState.classList.add("hidden");
    tableContainer.classList.add("hidden");
  }

  function showEmpty() {
    loadingState.classList.add("hidden");
    emptyState.classList.remove("hidden");
    tableContainer.classList.add("hidden");
  }

  function showTable() {
    loadingState.classList.add("hidden");
    emptyState.classList.add("hidden");
    tableContainer.classList.remove("hidden");
  }

  // ── Fetch & render ────────────────────────────────────────────
  async function loadSessions(page) {
    currentPage = page || currentPage;
    showLoading();

    const params = new URLSearchParams({
      page: currentPage,
      limit: currentLimit,
    });
    if (currentSearch) params.set("search", currentSearch);
    if (currentStatus) params.set("status", currentStatus);

    try {
      const res = await fetch(`/api/sessions?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();

      const sessions = json.data || [];
      const pagination = json.pagination || {};
      totalPages = pagination.pages || 1;

      if (sessions.length === 0) {
        showEmpty();
        return;
      }

      renderTable(sessions);
      updatePagination(pagination);
      showTable();
    } catch (err) {
      console.error("Failed to load sessions:", err);
      showEmpty();
    }
  }

  function renderTable(sessions) {
    tbody.innerHTML = "";
    sessions.forEach((s) => {
      const tr = document.createElement("tr");
      const name = s.friendly_name || `Session #${s.id}`;
      const cmd = truncate(s.server_command, 55);

      tr.innerHTML = `
        <td class="px-5 py-4 whitespace-nowrap">
          <div class="font-semibold text-white text-sm">${escHtml(name)}</div>
          <div class="text-xs text-gray-500 font-mono mt-0.5">#${s.id}</div>
        </td>
        <td class="px-5 py-4 max-w-xs">
          <code class="text-xs text-gray-400 font-mono" title="${escHtml(s.server_command || '')}">${escHtml(cmd)}</code>
        </td>
        <td class="px-5 py-4 whitespace-nowrap">${statusBadge(s.status)}</td>
        <td class="px-5 py-4 whitespace-nowrap text-xs text-gray-400">
          <div title="Messages">📨 ${s.total_messages ?? 0}</div>
          <div title="Duration" class="mt-0.5">⏱ ${formatDuration(s.duration_seconds)}</div>
        </td>
        <td class="px-5 py-4 whitespace-nowrap text-xs text-gray-400">${formatDate(s.started_at)}</td>
        <td class="px-5 py-4 whitespace-nowrap text-right text-sm">
          <button
            class="text-red-400 hover:text-red-300 transition-colors ml-3"
            data-delete-id="${s.id}"
            data-delete-name="${escHtml(name)}"
            title="Delete session"
          >🗑</button>
        </td>
      `;

      // Row click → detail page (not on delete button)
      tr.addEventListener("click", (e) => {
        if (e.target.closest("[data-delete-id]")) return;
        window.location.href = `/session/${s.id}`;
      });

      tbody.appendChild(tr);
    });

    // Wire delete buttons
    tbody.querySelectorAll("[data-delete-id]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openDeleteModal(parseInt(btn.dataset.deleteId), btn.dataset.deleteName);
      });
    });
  }

  function updatePagination(pagination) {
    const { page, limit, total, pages } = pagination;
    const start = (page - 1) * limit + 1;
    const end = Math.min(page * limit, total);
    if (pageInfo) pageInfo.textContent = `Page ${page} of ${pages}`;
    if (totalInfo) totalInfo.textContent = `${start}–${end} of ${total} sessions`;
    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = page >= pages;
  }

  // ── Modals ─────────────────────────────────────────────────────
  function openDeleteModal(id, name) {
    pendingDeleteId = id;
    if (deleteName) deleteName.textContent = name;
    if (deleteModal) deleteModal.classList.remove("hidden");
  }

  function closeDeleteModal() {
    pendingDeleteId = null;
    if (deleteModal) deleteModal.classList.add("hidden");
  }

  // ── Escape HTML ───────────────────────────────────────────────
  function escHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Event listeners ───────────────────────────────────────────
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        currentSearch = searchInput.value.trim();
        loadSessions(1);
      }, 300);
    });
  }

  if (statusFilter) {
    statusFilter.addEventListener("change", () => {
      currentStatus = statusFilter.value;
      loadSessions(1);
    });
  }

  if (limitSelect) {
    limitSelect.addEventListener("change", () => {
      currentLimit = parseInt(limitSelect.value, 10);
      loadSessions(1);
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => loadSessions(1));
  }

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (currentPage > 1) loadSessions(currentPage - 1);
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (currentPage < totalPages) loadSessions(currentPage + 1);
    });
  }

  if (newSessionBtn && modal) {
    newSessionBtn.addEventListener("click", () => modal.classList.remove("hidden"));
  }

  if (closeModalBtn && modal) {
    closeModalBtn.addEventListener("click", () => modal.classList.add("hidden"));
  }

  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.add("hidden");
    });
  }

  if (cancelDeleteBtn) cancelDeleteBtn.addEventListener("click", closeDeleteModal);

  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener("click", async () => {
      if (!pendingDeleteId) return;
      try {
        const res = await fetch(`/api/sessions/${pendingDeleteId}`, { method: "DELETE" });
        if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
        closeDeleteModal();
        loadSessions(1);
      } catch (err) {
        console.error("Delete failed:", err);
        closeDeleteModal();
      }
    });
  }

  // ── Init ──────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => loadSessions(1));
})();
