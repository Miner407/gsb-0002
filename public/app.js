const API = "/api";
let state = {
    users: [],
    tools: [],
    orders: [],
    categories: [],
    currentUserId: null,
    currentToolId: null,
    filters: { status: "", category: "", keyword: "" },
    orderStatusFilter: "",
};

function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

async function api(url, options = {}) {
    const res = await fetch(API + url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(data.error || `请求失败 (${res.status})`);
    }
    return data;
}

function toast(msg, type = "info") {
    const el = $("#toast");
    el.className = `toast ${type} show`;
    el.textContent = msg;
    setTimeout(() => el.classList.remove("show"), 2600);
}

function statusText(s) {
    return { available: "可借用", borrowed: "已借出", returned: "已归还" }[s] || s;
}

function statusClass(s) {
    return `status-${s}`;
}

async function loadUsers() {
    state.users = await api("/users");
    renderUserSelects();
}

function renderUserSelects() {
    const opts = state.users.map(u => `<option value="${u.id}">${u.name}</option>`).join("");
    const currentOpts = `<option value="">请选择用户</option>` + state.users.map(u =>
        `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}</option>`
    ).join("");

    $("#currentUserSelect").innerHTML = currentOpts;
    $("#toolOwner").innerHTML = opts;

    const currentBorrower = $("#borrowerSelect");
    if (currentBorrower) {
        currentBorrower.innerHTML = state.users
            .filter(u => u.id != state._currentToolOwnerId)
            .map(u => `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}</option>`)
            .join("");
    }
}

async function loadCategories() {
    state.categories = await api("/tools/categories");
    const sel = $("#categoryFilter");
    sel.innerHTML = `<option value="">全部分类</option>` +
        state.categories.map(c => `<option value="${c}">${c}</option>`).join("");
}

async function loadTools() {
    const params = new URLSearchParams();
    Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    const qs = params.toString();
    state.tools = await api("/tools" + (qs ? `?${qs}` : ""));
    renderTools();
}

function renderTools() {
    const grid = $("#toolsGrid");
    const empty = $("#emptyTools");

    if (state.tools.length === 0) {
        grid.innerHTML = "";
        empty.style.display = "block";
        return;
    }
    empty.style.display = "none";

    grid.innerHTML = state.tools.map(t => `
        <div class="tool-card" data-id="${t.id}">
            <img class="tool-image" src="${t.image_url}" alt="${t.name}" onerror="this.style.background='#e2e8f0';this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2280%22>🛠️</text></svg>'">
            <div class="tool-body">
                <div class="tool-title">
                    <span>${escapeHtml(t.name)}</span>
                    <span class="tool-category">${escapeHtml(t.category || "-")}</span>
                </div>
                <div class="tool-desc">${escapeHtml(t.description || "暂无描述")}</div>
                <div class="tool-footer">
                    <span class="owner">👤 ${escapeHtml(t.owner_name || "-")}</span>
                    <span class="status-badge ${statusClass(t.status)}">${statusText(t.status)}</span>
                </div>
            </div>
        </div>
    `).join("");

    $$("#toolsGrid .tool-card").forEach(card => {
        card.addEventListener("click", () => openDetail(+card.dataset.id));
    });
}

async function loadOrders() {
    const qs = state.orderStatusFilter ? `?status=${state.orderStatusFilter}` : "";
    state.orders = await api("/orders" + qs);
    renderOrders();
}

function renderOrders() {
    const list = $("#ordersList");
    const empty = $("#emptyOrders");

    if (state.orders.length === 0) {
        list.innerHTML = "";
        empty.style.display = "block";
        return;
    }
    empty.style.display = "none";

    list.innerHTML = state.orders.map(o => {
        const canReturn = o.status === "borrowed" &&
            (o.borrower_id == state.currentUserId || o.owner_id == state.currentUserId);
        return `
        <div class="order-item" data-tool-id="${o.tool_id}" data-order-id="${o.id}">
            <div class="order-info">
                <div class="order-tool">🧰 ${escapeHtml(o.tool_name || "-")}</div>
                <div class="order-meta">
                    <span>借用人：${escapeHtml(o.borrower_name || "-")}</span>
                    <span>所有人：${escapeHtml(o.owner_name || "-")}</span>
                    <span>借出：${o.borrowed_at || "-"}</span>
                    ${o.returned_at ? `<span>归还：${o.returned_at}</span>` : ""}
                </div>
            </div>
            <div class="order-actions">
                <span class="status-badge ${statusClass(o.status)}">${statusText(o.status)}</span>
                ${canReturn ? `<button class="btn btn-warning btn-small return-btn" data-tool-id="${o.tool_id}">归还</button>` : ""}
            </div>
        </div>`;
    }).join("");

    $$(".return-btn", list).forEach(btn => {
        btn.addEventListener("click", e => {
            e.stopPropagation();
            returnTool(+btn.dataset.toolId);
        });
    });
}

function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function openDetail(toolId) {
    state.currentToolId = toolId;
    const { tool, history } = await api(`/tools/${toolId}`);

    $("#detailTitle").textContent = tool.name;
    state._currentToolOwnerId = tool.owner_id;

    const canBorrow = tool.status === "available" && state.currentUserId && state.currentUserId != tool.owner_id;
    const canReturn = tool.status === "borrowed" && state.currentUserId;

    const historyHtml = history.length
        ? `<div class="history-list">${history.map(h => `
            <div class="history-item">
                <div class="history-info">
                    <div class="history-user">👤 ${escapeHtml(h.borrower_name || "-")}</div>
                    <div class="history-time">借出：${h.borrowed_at || "-"} ｜ ${h.returned_at ? "归还：" + h.returned_at : "借用中"}</div>
                </div>
                <span class="status-badge ${statusClass(h.status)}">${statusText(h.status)}</span>
            </div>`).join("")}</div>`
        : `<p style="color:#a0aec0;text-align:center;padding:20px;">暂无借还记录</p>`;

    $("#detailBody").innerHTML = `
        <div class="detail-header">
            <img class="detail-image" src="${tool.image_url}" alt="${tool.name}" onerror="this.style.background='#e2e8f0';this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2280%22>🛠️</text></svg>'">
            <div class="detail-main">
                <h2>${escapeHtml(tool.name)}
                    <span class="tool-category">${escapeHtml(tool.category || "-")}</span>
                    <span class="status-badge ${statusClass(tool.status)}">${statusText(tool.status)}</span>
                </h2>
                <div class="detail-meta">
                    <div class="row"><span class="label">所有人</span><span>👤 ${escapeHtml(tool.owner_name || "-")}${tool.owner_phone ? "（" + tool.owner_phone + "）" : ""}</span></div>
                    <div class="row"><span class="label">发布时间</span><span>${tool.created_at || "-"}</span></div>
                </div>
                ${tool.description ? `<div class="detail-desc">${escapeHtml(tool.description)}</div>` : ""}
                <div class="detail-actions">
                    ${canBorrow ? `<button class="btn btn-primary" id="detailBorrowBtn">📥 申请借用</button>` : ""}
                    ${canReturn ? `<button class="btn btn-warning" id="detailReturnBtn">🔄 归还工具</button>` : ""}
                    ${tool.status === "available" && (!state.currentUserId || state.currentUserId == tool.owner_id) ? `<button class="btn btn-secondary" disabled>${tool.status === "available" && state.currentUserId == tool.owner_id ? "不能借用自己的工具" : "请先选择身份后借用"}</button>` : ""}
                    ${tool.status === "borrowed" && !state.currentUserId ? `<button class="btn btn-secondary" disabled>登录后可归还</button>` : ""}
                </div>
            </div>
        </div>
        <div style="margin-top: 28px;">
            <div class="section-title">📋 借还记录</div>
            ${historyHtml}
        </div>
    `;

    openModal("detailModal");

    const borrowBtn = $("#detailBorrowBtn");
    if (borrowBtn) borrowBtn.addEventListener("click", () => openBorrowModal(tool));
    const returnBtn = $("#detailReturnBtn");
    if (returnBtn) returnBtn.addEventListener("click", () => returnTool(tool.id));
}

async function openBorrowModal(tool) {
    state._currentToolOwnerId = tool.owner_id;
    $("#borrowInfo").innerHTML = `
        <div class="row"><span>工具名称</span><span>${escapeHtml(tool.name)}</span></div>
        <div class="row"><span>分类</span><span>${escapeHtml(tool.category || "-")}</span></div>
        <div class="row"><span>所有人</span><span>${escapeHtml(tool.owner_name || "-")}</span></div>
    `;
    $("#borrowerSelect").innerHTML = state.users
        .filter(u => u.id != tool.owner_id)
        .map(u => `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}</option>`)
        .join("");
    state._pendingBorrowToolId = tool.id;
    openModal("borrowModal");
}

async function submitBorrow() {
    const toolId = state._pendingBorrowToolId;
    const borrowerId = $("#borrowerSelect").value;
    if (!borrowerId) {
        toast("请选择借用人", "warning");
        return;
    }
    try {
        await api(`/tools/${toolId}/borrow`, {
            method: "POST",
            body: JSON.stringify({ borrower_id: +borrowerId }),
        });
        toast("🎉 借用成功！请妥善保管", "success");
        closeModal("borrowModal");
        closeModal("detailModal");
        state.currentUserId = +borrowerId;
        renderUserSelects();
        await refreshAll();
    } catch (e) {
        toast(e.message, "error");
    }
}

async function returnTool(toolId) {
    if (!confirm("确认归还该工具吗？")) return;
    try {
        await api(`/tools/${toolId}/return`, { method: "POST" });
        toast("✅ 归还成功！感谢您的配合", "success");
        closeModal("detailModal");
        await refreshAll();
    } catch (e) {
        toast(e.message, "error");
    }
}

async function submitPublish() {
    const name = $("#toolName").value.trim();
    const category = $("#toolCategory").value.trim();
    const description = $("#toolDesc").value.trim();
    const ownerId = $("#toolOwner").value;
    if (!name) { toast("请填写工具名称", "warning"); return; }
    if (!ownerId) { toast("请选择发布人", "warning"); return; }
    try {
        await api("/tools", {
            method: "POST",
            body: JSON.stringify({ name, category, description, owner_id: +ownerId }),
        });
        toast("🚀 工具发布成功", "success");
        closeModal("publishModal");
        ["#toolName", "#toolCategory", "#toolDesc"].forEach(s => $(s).value = "");
        await refreshAll();
    } catch (e) {
        toast(e.message, "error");
    }
}

async function submitUser() {
    const name = $("#newUserName").value.trim();
    const phone = $("#newUserPhone").value.trim();
    if (!name) { toast("请填写姓名", "warning"); return; }
    try {
        const user = await api("/users", {
            method: "POST",
            body: JSON.stringify({ name, phone }),
        });
        toast("👤 注册成功", "success");
        state.currentUserId = user.id;
        closeModal("userModal");
        $("#newUserName").value = "";
        $("#newUserPhone").value = "";
        await loadUsers();
        await loadCategories();
    } catch (e) {
        toast(e.message, "error");
    }
}

function openModal(id) { $("#" + id).classList.add("active"); }
function closeModal(id) { $("#" + id).classList.remove("active"); }

async function refreshAll() {
    await Promise.all([loadTools(), loadOrders(), loadCategories()]);
}

function bindEvents() {
    $$(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            $$(".tab").forEach(t => t.classList.remove("active"));
            $$(".tab-content").forEach(tc => tc.classList.remove("active"));
            tab.classList.add("active");
            $("#" + tab.dataset.tab + "Tab").classList.add("active");
        });
    });

    $("#publishBtn").addEventListener("click", () => openModal("publishModal"));
    $("#submitPublish").addEventListener("click", submitPublish);
    $("#submitBorrow").addEventListener("click", submitBorrow);
    $("#submitUser").addEventListener("click", submitUser);
    $("#addUserBtn").addEventListener("click", () => openModal("userModal"));

    $$("[data-close]").forEach(btn => {
        btn.addEventListener("click", () => closeModal(btn.dataset.close));
    });
    $$(".modal-overlay").forEach(ov => {
        ov.addEventListener("click", e => {
            if (e.target === ov) ov.classList.remove("active");
        });
    });

    $("#statusFilter").addEventListener("change", e => {
        state.filters.status = e.target.value;
        loadTools();
    });
    $("#categoryFilter").addEventListener("change", e => {
        state.filters.category = e.target.value;
        loadTools();
    });
    let searchTimer;
    $("#searchInput").addEventListener("input", e => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            state.filters.keyword = e.target.value.trim();
            loadTools();
        }, 280);
    });
    $("#orderStatusFilter").addEventListener("change", e => {
        state.orderStatusFilter = e.target.value;
        loadOrders();
    });
    $("#currentUserSelect").addEventListener("change", e => {
        state.currentUserId = e.target.value ? +e.target.value : null;
    });
}

async function init() {
    bindEvents();
    await Promise.all([loadUsers(), loadCategories()]);
    if (state.users.length) {
        state.currentUserId = state.users[0].id;
        renderUserSelects();
    }
    await refreshAll();
}

document.addEventListener("DOMContentLoaded", init);
