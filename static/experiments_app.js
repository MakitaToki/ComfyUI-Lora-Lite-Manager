import { fetchExperimentRun, fetchExperimentRuns, refreshExperimentRun } from "./experiment_api.js";

const state = {
    runs: [],
    selectedRun: null,
};

const els = {
    summary: document.querySelector("#summary"),
    refreshBtn: document.querySelector("#refreshBtn"),
    runList: document.querySelector("#runList"),
    emptyState: document.querySelector("#emptyState"),
    runDetails: document.querySelector("#runDetails"),
    runStatus: document.querySelector("#runStatus"),
    runTitle: document.querySelector("#runTitle"),
    runMeta: document.querySelector("#runMeta"),
    runProgress: document.querySelector("#runProgress"),
    runSummary: document.querySelector("#runSummary"),
    resultGrid: document.querySelector("#resultGrid"),
    resultDialog: document.querySelector("#resultDialog"),
    resultTitle: document.querySelector("#resultTitle"),
    resultSubtitle: document.querySelector("#resultSubtitle"),
    resultBody: document.querySelector("#resultBody"),
    closeResultBtn: document.querySelector("#closeResultBtn"),
    toast: document.querySelector("#toast"),
};

init();

async function init() {
    bindEvents();
    await loadRuns();
    const runId = new URLSearchParams(window.location.search).get("run_id");
    if (runId) {
        await selectRun(runId);
    } else if (state.runs[0]) {
        await selectRun(state.runs[0].run_id);
    }
}

function bindEvents() {
    els.refreshBtn.addEventListener("click", async () => {
        if (state.selectedRun) {
            await refreshSelectedRun();
        } else {
            await loadRuns();
        }
    });
    els.closeResultBtn.addEventListener("click", closeResultDialog);
    els.resultDialog.addEventListener("click", (event) => {
        if (event.target === els.resultDialog) {
            closeResultDialog();
        }
    });
}

async function loadRuns() {
    try {
        const result = await fetchExperimentRuns();
        state.runs = result.runs || [];
        els.summary.textContent = `${state.runs.length} saved runs`;
        renderRunList();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function selectRun(runId) {
    try {
        const result = await fetchExperimentRun(runId);
        state.selectedRun = result.run;
        window.history.replaceState(null, "", `/experiments-lite?run_id=${encodeURIComponent(runId)}`);
        renderRunList();
        renderRun();
    } catch (error) {
        showToast(error.message, true);
    }
}

async function refreshSelectedRun() {
    if (!state.selectedRun) {
        return;
    }
    els.refreshBtn.disabled = true;
    els.refreshBtn.textContent = "Refreshing...";
    try {
        const result = await refreshExperimentRun(state.selectedRun.run_id);
        state.selectedRun = result.run;
        await loadRuns();
        renderRun();
        showToast("Run refreshed");
    } catch (error) {
        showToast(error.message, true);
    } finally {
        els.refreshBtn.disabled = false;
        els.refreshBtn.textContent = "Refresh";
    }
}

function renderRunList() {
    els.runList.replaceChildren();
    if (!state.runs.length) {
        const empty = document.createElement("div");
        empty.className = "details-empty";
        empty.textContent = "No saved runs yet.";
        els.runList.append(empty);
        return;
    }
    for (const run of state.runs) {
        const button = document.createElement("button");
        button.className = "run-list-item";
        button.classList.toggle("active", state.selectedRun?.run_id === run.run_id);
        button.type = "button";
        button.addEventListener("click", () => selectRun(run.run_id));
        button.innerHTML = `
            <strong>${escapeHtml(run.run_id)}</strong>
            <span>${escapeHtml(run.status)} · ${run.completed || 0}/${run.total || 0} completed</span>
            <span>${escapeHtml(run.created_at || "")}</span>
        `;
        els.runList.append(button);
    }
}

function renderRun() {
    const run = state.selectedRun;
    els.emptyState.hidden = Boolean(run);
    els.runDetails.hidden = !run;
    if (!run) {
        return;
    }

    const preview = run.preview || {};
    const summary = preview.summary || {};
    const completed = (run.submissions || []).filter((item) => item.status === "completed").length;
    els.runStatus.textContent = run.status;
    els.runTitle.textContent = run.run_id;
    els.runMeta.textContent = `${run.created_at} · ${summary.total || 0} cases · ${run.workflow || ""}`;
    els.runProgress.textContent = `${completed} / ${summary.total || 0}`;
    els.runSummary.innerHTML = `
        <div><strong>${summary.total || 0}</strong><span>cases</span></div>
        <div><strong>${preview.prompt_variants?.length || 0}</strong><span>prompt variants</span></div>
        <div><strong>${preview.lora_combos?.length || 0}</strong><span>LoRA combos</span></div>
        <div><strong>${preview.strengths?.join(", ") || "-"}</strong><span>strengths</span></div>
    `;
    renderResultGrid(run);
}

function renderResultGrid(run) {
    const preview = run.preview || {};
    const submissions = run.submissions || [];
    const byVariant = groupBy(submissions, (item) => item.case?.prompt_variant_id || "unknown");
    els.resultGrid.replaceChildren();

    for (const variant of preview.prompt_variants || []) {
        const section = document.createElement("section");
        section.className = "result-section";
        section.innerHTML = `
            <div class="result-section-head">
                <div>
                    <h2>${escapeHtml(variant.label)}</h2>
                    <p>${escapeHtml(compact(variant.positive, 240))}</p>
                </div>
            </div>
        `;
        const grid = document.createElement("div");
        grid.className = "result-cards";
        for (const submission of byVariant.get(variant.id) || []) {
            grid.append(resultCard(submission));
        }
        section.append(grid);
        els.resultGrid.append(section);
    }
}

function resultCard(submission) {
    const card = document.createElement("button");
    const caseData = submission.case || {};
    const output = (submission.outputs || [])[0];
    card.className = "result-card";
    card.type = "button";
    card.addEventListener("click", () => openResultDialog(submission));
    if (output?.url) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = output.url;
        img.alt = caseData.case_id || "result";
        card.append(img);
    } else {
        const placeholder = document.createElement("div");
        placeholder.className = "result-placeholder";
        placeholder.textContent = submission.status || "submitted";
        card.append(placeholder);
    }
    const body = document.createElement("div");
    body.className = "result-card-body";
    body.innerHTML = `
        <strong>${escapeHtml(caseData.lora_combo_label || "LoRA combo")}</strong>
        <span>strength ${escapeHtml(String(caseData.strength ?? "-"))} · seed ${escapeHtml(String(caseData.seed ?? "-"))}</span>
        <span>${escapeHtml(submission.status || "")}</span>
    `;
    card.append(body);
    return card;
}

function openResultDialog(submission) {
    const caseData = submission.case || {};
    const output = (submission.outputs || [])[0];
    els.resultTitle.textContent = caseData.case_id || "Result";
    els.resultSubtitle.textContent = `${caseData.lora_combo_label || ""} · strength ${caseData.strength ?? "-"} · seed ${caseData.seed ?? "-"}`;
    els.resultBody.innerHTML = `
        ${output?.url ? `<img class="detail-image" src="${escapeAttr(output.url)}" alt="">` : `<div class="empty"><strong>${escapeHtml(submission.status || "No output yet")}</strong><span>${escapeHtml(submission.error || "Refresh after ComfyUI completes the prompt.")}</span></div>`}
        <div class="detail-section"><h3>Positive prompt</h3><p>${escapeHtml(caseData.prompt?.positive || "")}</p></div>
        <div class="detail-section"><h3>Negative prompt</h3><p>${escapeHtml(caseData.prompt?.negative || "")}</p></div>
        <div class="detail-section"><h3>Tags</h3><p>${escapeHtml((caseData.prompt?.tags || []).join(", "))}</p></div>
        <div class="detail-section"><h3>Unmatched terms</h3><p>${escapeHtml((caseData.prompt?.unmatched_terms || []).join(", ") || "-")}</p></div>
        <div class="detail-section"><h3>ComfyUI</h3><p>${escapeHtml(submission.prompt_id || "-")}</p></div>
    `;
    els.resultDialog.hidden = false;
    document.body.classList.add("dialog-open");
}

function closeResultDialog() {
    els.resultDialog.hidden = true;
    document.body.classList.remove("dialog-open");
}

function groupBy(items, getKey) {
    const groups = new Map();
    for (const item of items) {
        const key = getKey(item);
        if (!groups.has(key)) {
            groups.set(key, []);
        }
        groups.get(key).push(item);
    }
    return groups;
}

function compact(value, length = 140) {
    return String(value || "").replace(/\s+/g, " ").slice(0, length);
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
}

function showToast(message, isError = false) {
    els.toast.textContent = message;
    els.toast.classList.toggle("error", isError);
    els.toast.hidden = false;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        els.toast.hidden = true;
    }, 3600);
}
