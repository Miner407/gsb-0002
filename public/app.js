const API = "/api";
let state = {
    users: [],
    tools: [],
    orders: [],
    reservations: [],
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
    return { available: "可借用", borrowed: "已借出", reserved: "待取用", returned: "已归还" }[s] || s;
}

function statusClass(s) {
    return `status-${s}`;
}

function creditClass(score) {
    if (score >= 90) return "credit-good";
    if (score >= 60) return "credit-medium";
    return "credit-bad";
}

function creditLabel(score) {
    if (score >= 90) return "优秀";
    if (score >= 60) return "一般";
    return "较差";
}

async function loadUsers() {
    state.users = await api("/users");
    renderUserSelects();
    renderCurrentCredit();
}

function renderCurrentCredit() {
    const badge = $("#currentCreditBadge");
    const scoreEl = $("#currentCreditScore");
    if (!state.currentUserId) {
        badge.style.display = "none";
        return;
    }
    const user = state.users.find(u => u.id == state.currentUserId);
    if (!user) {
        badge.style.display = "none";
        return;
    }
    badge.style.display = "inline-flex";
    badge.className = `credit-badge ${creditClass(user.credit_score)}`;
    scoreEl.textContent = user.credit_score;
}

function renderReservationNotice() {
    const notice = $("#reservationNotice");
    const text = $("#reservationNoticeText");
    if (!state.currentUserId || !state.reservations || state.reservations.length === 0) {
        notice.style.display = "none";
        return;
    }
    const confirmedCount = state.reservations.filter(r => r.status === "confirmed").length;
    const pendingCount = state.reservations.filter(r => r.status === "pending").length;

    if (confirmedCount > 0) {
        notice.style.display = "inline-flex";
        notice.className = "reservation-notice reservation-notice-urgent";
        if (confirmedCount === 1) {
            const r = state.reservations.find(r => r.status === "confirmed");
            text.textContent = `${r.tool_name} 轮到你了！请尽快取用`;
        } else {
            text.textContent = `${confirmedCount}个待取用，${pendingCount}个排队中`;
        }
    } else if (pendingCount > 0) {
        notice.style.display = "inline-flex";
        notice.className = "reservation-notice";
        text.textContent = `${pendingCount}个预约排队中`;
    } else {
        notice.style.display = "none";
    }
}

function renderUserSelects() {
    const opts = state.users.map(u =>
        `<option value="${u.id}">${u.name}（⭐${u.credit_score ?? 100}）</option>`
    ).join("");
    const currentOpts = `<option value="">请选择用户</option>` + state.users.map(u =>
        `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}（⭐${u.credit_score ?? 100}）</option>`
    ).join("");

    $("#currentUserSelect").innerHTML = currentOpts;
    $("#toolOwner").innerHTML = opts;

    const currentBorrower = $("#borrowerSelect");
    if (currentBorrower) {
        currentBorrower.innerHTML = state.users
            .filter(u => u.id != state._currentToolOwnerId)
            .map(u => `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}（⭐${u.credit_score ?? 100}）</option>`)
            .join("");
    }

    const reserveUser = $("#reserveUserSelect");
    if (reserveUser) {
        reserveUser.innerHTML = state.users
            .filter(u => u.id != state._currentToolOwnerId)
            .map(u => `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}（⭐${u.credit_score ?? 100}）</option>`)
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

    grid.innerHTML = state.tools.map(t => {
        const isConfirmed = t.confirmed_reservation && t.confirmed_reservation.user_id == state.currentUserId;
        const resBadge = t.reservation_count > 0
            ? `<span class="reserve-count" title="${t.reservation_count}人预约排队">🔖 ${t.reservation_count}人预约</span>`
            : "";
        const confirmedBadge = t.confirmed_reservation
            ? `<div class="confirmed-notice ${isConfirmed ? 'confirmed-notice-mine' : ''}">
                 🔔 已为 <strong>${escapeHtml(t.confirmed_reservation.user_name)}</strong> 保留，请尽快取用
               </div>`
            : "";
        const creditHtml = t.owner_credit != null
            ? `<span class="credit-mini ${creditClass(t.owner_credit)}" title="信用分：${t.owner_credit}">⭐${t.owner_credit}</span>`
            : "";
        const cardClass = t.status === "reserved" ? "tool-card tool-card-reserved" : "tool-card";
        return `
        <div class="${cardClass}" data-id="${t.id}">
            <div class="tool-image-wrap">
                <img class="tool-image" src="${t.image_url}" alt="${t.name}" onerror="this.style.background='#e2e8f0';this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2280%22>🛠️</text></svg>'">
                <span class="tool-status-overlay status-badge ${statusClass(t.status)}">${statusText(t.status)}</span>
            </div>
            <div class="tool-body">
                <div class="tool-title">
                    <span>${escapeHtml(t.name)}</span>
                    <span class="tool-category">${escapeHtml(t.category || "-")}</span>
                </div>
                <div class="tool-desc">${escapeHtml(t.description || "暂无描述")}</div>
                ${confirmedBadge}
                <div class="tool-footer">
                    <span class="owner">👤 ${escapeHtml(t.owner_name || "-")} ${creditHtml} ${resBadge}</span>
                </div>
            </div>
        </div>`;
    }).join("");

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

async function loadReservations() {
    if (!state.currentUserId) {
        state.reservations = [];
        renderReservations();
        return;
    }
    state.reservations = await api(`/reservations?user_id=${state.currentUserId}`);
    renderReservations();
}

function renderReservations() {
    const list = $("#reservationsList");
    const empty = $("#emptyReservations");

    if (state.reservations.length === 0) {
        list.innerHTML = "";
        empty.style.display = "block";
        renderReservationNotice();
        return;
    }
    empty.style.display = "none";

    list.innerHTML = state.reservations.map(r => {
        const isConfirmed = r.status === "confirmed";
        const statusBadge = isConfirmed
            ? `<span class="status-badge status-confirmed">🔔 待取用</span>`
            : `<span class="status-badge status-pending">⏳ 排队中</span>`;
        const actionBtn = isConfirmed
            ? `<button class="btn btn-success btn-small pickup-btn" data-id="${r.id}">📥 取用工具</button>`
            : "";
        return `
        <div class="reservation-item ${isConfirmed ? "reservation-confirmed" : ""}" data-id="${r.id}">
            <div class="order-info">
                <div class="order-tool">🧰 ${escapeHtml(r.tool_name || "-")}</div>
                <div class="order-meta">
                    <span>所有人：${escapeHtml(r.owner_name || "-")}</span>
                    <span>预约时间：${r.created_at || "-"}</span>
                    ${isConfirmed ? `<span class="confirmed-highlight">🔔 轮到你了！请尽快取用</span>` : ""}
                </div>
            </div>
            <div class="order-actions">
                ${statusBadge}
                ${actionBtn}
                <button class="btn btn-secondary btn-small cancel-reserve-btn" data-id="${r.id}" data-confirmed="${isConfirmed}">取消预约</button>
            </div>
        </div>`;
    }).join("");

    $$(".pickup-btn", list).forEach(btn => {
        btn.addEventListener("click", e => {
            e.stopPropagation();
            pickupReservation(+btn.dataset.id);
        });
    });

    $$(".cancel-reserve-btn", list).forEach(btn => {
        btn.addEventListener("click", e => {
            e.stopPropagation();
            const isConfirmed = btn.dataset.confirmed === "true";
            cancelReservation(+btn.dataset.id, isConfirmed);
        });
    });

    renderReservationNotice();
}

function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function openDetail(toolId) {
    state.currentToolId = toolId;
    const { tool, history, reservations } = await api(`/tools/${toolId}`);

    $("#detailTitle").textContent = tool.name;
    state._currentToolOwnerId = tool.owner_id;

    const canBorrow = tool.status === "available" && state.currentUserId && state.currentUserId != tool.owner_id;
    const canReturn = tool.status === "borrowed" && state.currentUserId;
    const canReserve = (tool.status === "borrowed" || tool.status === "reserved") && state.currentUserId && state.currentUserId != tool.owner_id;
    const canPickup = tool.status === "reserved" && state.currentUserId && reservations.some(r => r.status === "confirmed" && r.user_id == state.currentUserId);

    const reservationHtml = reservations.length
        ? `<div class="reservation-queue">
            <div class="section-title">🔖 预约队列（${reservations.length}人）</div>
            ${reservations.map((r, i) => `
                <div class="history-item ${r.status === 'confirmed' ? 'reservation-confirmed-item' : ''}">
                    <div class="history-info">
                        <div class="history-user">${i + 1}. 👤 ${escapeHtml(r.user_name || "-")}
                            <span class="credit-mini ${creditClass(r.user_credit ?? 100)}">⭐${r.user_credit ?? 100}</span>
                        </div>
                        <div class="history-time">预约时间：${r.created_at || "-"}
                            ${r.status === 'confirmed' ? ' ｜ <span class="confirmed-highlight">🔔 待取用</span>' : ''}
                        </div>
                    </div>
                    ${r.status === 'confirmed' ? '<span class="status-badge status-confirmed">🔔 待取用</span>' : '<span class="status-badge status-pending">⏳ 排队中</span>'}
                </div>`).join("")}
           </div>`
        : "";

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

    const ownerCredit = tool.owner_credit != null
        ? ` <span class="credit-mini ${creditClass(tool.owner_credit)}">⭐${tool.owner_credit}</span>`
        : "";

    $("#detailBody").innerHTML = `
        <div class="detail-header">
            <img class="detail-image" src="${tool.image_url}" alt="${tool.name}" onerror="this.style.background='#e2e8f0';this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2280%22>🛠️</text></svg>'">
            <div class="detail-main">
                <h2>${escapeHtml(tool.name)}
                    <span class="tool-category">${escapeHtml(tool.category || "-")}</span>
                    <span class="status-badge ${statusClass(tool.status)}">${statusText(tool.status)}</span>
                </h2>
                <div class="detail-meta">
                    <div class="row"><span class="label">所有人</span><span>👤 ${escapeHtml(tool.owner_name || "-")}${ownerCredit}${tool.owner_phone ? "（" + tool.owner_phone + "）" : ""}</span></div>
                    <div class="row"><span class="label">发布时间</span><span>${tool.created_at || "-"}</span></div>
                </div>
                ${tool.description ? `<div class="detail-desc">${escapeHtml(tool.description)}</div>` : ""}
                <div class="detail-actions">
                    ${canBorrow ? `<button class="btn btn-primary" id="detailBorrowBtn">📥 申请借用</button>` : ""}
                    ${canPickup ? `<button class="btn btn-success" id="detailPickupBtn">📥 取用工具</button>` : ""}
                    ${canReserve ? `<button class="btn btn-primary" id="detailReserveBtn">🔖 预约借用</button>` : ""}
                    ${canReturn ? `<button class="btn btn-warning" id="detailReturnBtn">🔄 归还工具</button>` : ""}
                    ${tool.status === "available" && (!state.currentUserId || state.currentUserId == tool.owner_id) ? `<button class="btn btn-secondary" disabled>${tool.status === "available" && state.currentUserId == tool.owner_id ? "不能借用自己的工具" : "请先选择身份后借用"}</button>` : ""}
                    ${tool.status === "borrowed" && !canReserve && !canReturn ? `<button class="btn btn-secondary" disabled>${state.currentUserId ? "不能借用自己的工具" : "请先选择身份"}</button>` : ""}
                </div>
            </div>
        </div>
        ${reservationHtml}
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
    const reserveBtn = $("#detailReserveBtn");
    if (reserveBtn) reserveBtn.addEventListener("click", () => openReserveModal(tool));
    const pickupBtn = $("#detailPickupBtn");
    if (pickupBtn) pickupBtn.addEventListener("click", () => {
        const confirmed = reservations.find(r => r.status === "confirmed" && r.user_id == state.currentUserId);
        if (confirmed) pickupReservation(confirmed.id);
    });
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
        .map(u => `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}（⭐${u.credit_score ?? 100}）</option>`)
        .join("");
    state._pendingBorrowToolId = tool.id;
    openModal("borrowModal");
}

async function openReserveModal(tool) {
    state._currentToolOwnerId = tool.owner_id;
    $("#reserveInfo").innerHTML = `
        <div class="row"><span>工具名称</span><span>${escapeHtml(tool.name)}</span></div>
        <div class="row"><span>分类</span><span>${escapeHtml(tool.category || "-")}</span></div>
        <div class="row"><span>所有人</span><span>${escapeHtml(tool.owner_name || "-")}</span></div>
        <div class="row"><span>当前状态</span><span>${statusText(tool.status)}</span></div>
    `;
    $("#reserveUserSelect").innerHTML = state.users
        .filter(u => u.id != tool.owner_id)
        .map(u => `<option value="${u.id}" ${u.id == state.currentUserId ? "selected" : ""}>${u.name}（⭐${u.credit_score ?? 100}）</option>`)
        .join("");
    state._pendingReserveToolId = tool.id;
    openModal("reserveModal");
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

async function submitReserve() {
    const toolId = state._pendingReserveToolId;
    const userId = $("#reserveUserSelect").value;
    if (!userId) {
        toast("请选择预约人", "warning");
        return;
    }
    try {
        await api(`/tools/${toolId}/reserve`, {
            method: "POST",
            body: JSON.stringify({ user_id: +userId }),
        });
        toast("🔖 预约成功！工具归还后将按顺序通知", "success");
        closeModal("reserveModal");
        closeModal("detailModal");
        state.currentUserId = +userId;
        renderUserSelects();
        await refreshAll();
    } catch (e) {
        toast(e.message, "error");
    }
}

async function returnTool(toolId) {
    if (!confirm("确认归还该工具吗？")) return;
    try {
        const result = await api(`/tools/${toolId}/return`, { method: "POST" });
        if (result.is_overdue) {
            toast(`⚠️ 归还成功（逾期归还，信用分${result.credit_delta}）`, "warning");
        } else if (result.credit_delta) {
            toast(`✅ 归还成功！信用分+${result.credit_delta}`, "success");
        } else {
            toast("✅ 归还成功！感谢您的配合", "success");
        }
        closeModal("detailModal");
        await refreshAll();
    } catch (e) {
        toast(e.message, "error");
    }
}

async function pickupReservation(reservationId) {
    if (!confirm("确认取用该工具吗？取用后将开始借用计时。")) return;
    try {
        await api(`/reservations/${reservationId}/pickup`, { method: "POST" });
        toast("🎉 取用成功！请妥善保管，及时归还", "success");
        closeModal("detailModal");
        await refreshAll();
    } catch (e) {
        toast(e.message, "error");
    }
}

async function cancelReservation(reservationId, isConfirmed) {
    const penaltyMsg = isConfirmed ? "\n注意：取消待取用预约将扣除5分信用分" : "";
    if (!confirm(`确认取消该预约吗？${penaltyMsg}`)) return;
    try {
        const result = await api(`/reservations/${reservationId}/cancel`, {
            method: "POST",
            body: JSON.stringify({ user_id: state.currentUserId }),
        });
        if (result.credit_penalty < 0) {
            toast(`预约已取消（信用分${result.credit_penalty}）`, "warning");
        } else {
            toast("预约已取消", "success");
        }
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
    await Promise.all([loadTools(), loadOrders(), loadCategories(), loadReservations(), loadUsers()]);
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
    $("#submitReserve").addEventListener("click", submitReserve);
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
        renderCurrentCredit();
        loadReservations();
    });

    $("#currentCreditBadge").addEventListener("click", () => {
        if (state.currentUserId) {
            openCreditLogModal(state.currentUserId);
        }
    });
}

async function openCreditLogModal(userId) {
    const body = $("#creditLogBody");
    body.innerHTML = '<p style="text-align:center;color:#a0aec0;padding:20px;">加载中...</p>';
    openModal("creditLogModal");
    try {
        const logs = await api(`/users/${userId}/credit-logs`);
        const user = state.users.find(u => u.id == userId);
        if (logs.length === 0) {
            body.innerHTML = '<p style="text-align:center;color:#a0aec0;padding:40px;">暂无信用分变动记录</p>';
            return;
        }
        body.innerHTML = `
            <div style="margin-bottom:16px;padding:12px;background:#f7fafc;border-radius:10px;">
                <div style="font-size:14px;color:#718096;">当前信用分</div>
                <div style="font-size:28px;font-weight:700;color:${user ? (user.credit_score >= 90 ? '#059669' : user.credit_score >= 60 ? '#d97706' : '#dc2626') : '#2c3e50'};">
                    ⭐ ${user ? user.credit_score : '-'} 分
                    <span style="font-size:14px;font-weight:500;color:#718096;">（${user ? creditLabel(user.credit_score) : ''}）</span>
                </div>
            </div>
            <div class="section-title">最近变动记录</div>
            <div style="display:flex;flex-direction:column;gap:8px;">
                ${logs.map(log => `
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:#f7fafc;border-radius:8px;">
                        <div>
                            <div style="font-size:13px;font-weight:500;">${escapeHtml(log.reason)}</div>
                            <div style="font-size:12px;color:#a0aec0;">${log.created_at || '-'}</div>
                        </div>
                        <span style="font-weight:700;font-size:16px;color:${log.delta > 0 ? '#059669' : '#dc2626'};">
                            ${log.delta > 0 ? '+' : ''}${log.delta}
                        </span>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (e) {
        body.innerHTML = `<p style="text-align:center;color:#dc2626;padding:20px;">加载失败：${escapeHtml(e.message)}</p>`;
    }
}

async function init() {
    bindEvents();
    await Promise.all([loadUsers(), loadCategories()]);
    if (state.users.length) {
        state.currentUserId = state.users[0].id;
        renderUserSelects();
        renderCurrentCredit();
    }
    await refreshAll();
}

document.addEventListener("DOMContentLoaded", init);
