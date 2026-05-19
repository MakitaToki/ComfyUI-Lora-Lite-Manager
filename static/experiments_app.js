import { fetchExperimentRun, fetchExperimentRuns, refreshExperimentRun } from "./experiment_api.js";

const state = {
    runs: [],
    selectedRun: null,
    pollTimer: 0,
    isPolling: false,
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
    restoreRecipeBtn: document.querySelector("#restoreRecipeBtn"),
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
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopPolling();
        } else if (isLiveRun(state.selectedRun)) {
            schedulePoll(300);
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
        restartPolling();
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
        restartPolling();
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
        const stats = runListStats(run);
        const button = document.createElement("button");
        button.className = "run-list-item";
        button.classList.toggle("active", state.selectedRun?.run_id === run.run_id);
        button.type = "button";
        button.addEventListener("click", () => selectRun(run.run_id));
        button.innerHTML = `
            <strong>${escapeHtml(run.run_id)}</strong>
            <span>${escapeHtml(run.status)} · queued ${stats.queued} · running ${stats.running} · done ${stats.completed} · failed ${stats.error}</span>
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
    const stats = runListStats(run);
    els.runStatus.textContent = run.status;
    els.runTitle.textContent = run.run_id;
    els.runMeta.textContent = `${run.created_at} · ${summary.total || 0} cases · ${run.workflow || ""}`;
    els.runProgress.textContent = `${stats.completed} / ${stats.total}`;
    if (els.restoreRecipeBtn) {
        els.restoreRecipeBtn.href = `/recipe-lite?run_id=${encodeURIComponent(run.run_id)}`;
    }
    renderRunProgressSummary(run, preview, stats);
    renderResultGrid(run);
}

function runListStats(run) {
    const submissions = run.submissions || [];
    const total = run.total || run.preview?.summary?.total || submissions.length || 0;
    const pending = Math.max(0, total - submissions.length);
    const queued = run.queued ?? submissions.filter((item) => ["queued", "submitted"].includes(item.status)).length;
    const running = run.running ?? submissions.filter((item) => item.status === "running").length;
    const completed = run.completed ?? submissions.filter((item) => item.status === "completed").length;
    const error = run.error ?? submissions.filter((item) => item.status === "error").length;
    return {
        total,
        pending,
        queued,
        running,
        submitted: queued + running + completed + error,
        completed,
        error,
    };
}

function renderRunProgressSummary(run, preview, stats) {
    const percent = stats.total ? Math.round((stats.completed / stats.total) * 100) : 0;
    const active = activeSubmission(run);
    const segments = [
        { label: "完成", count: stats.completed, className: "done" },
        { label: "执行", count: stats.running, className: "running" },
        { label: "排队", count: stats.queued, className: "queued" },
        { label: "失败", count: stats.error, className: "error" },
    ];
    els.runSummary.className = "run-progress-overview";
    els.runSummary.innerHTML = `
        <div class="run-progress-main">
            <div class="run-progress-line">
                <div>
                    <span>当前进度</span>
                    <strong>${escapeHtml(String(stats.completed))} / ${escapeHtml(String(stats.total))}</strong>
                </div>
                <em>${escapeHtml(String(percent))}%</em>
            </div>
            <div class="experiment-progress-bar" role="img" aria-label="Run progress ${escapeAttr(`${stats.completed} of ${stats.total}`)}">
                ${segments.map((segment) => progressSegment(segment, stats.total)).join("")}
            </div>
            <div class="run-progress-counts">
                ${segments.map((segment) => `<span class="${segment.className}">${escapeHtml(segment.label)} ${escapeHtml(String(segment.count))}</span>`).join("")}
                <span>待提交 ${escapeHtml(String(stats.pending))}</span>
            </div>
        </div>
        <div class="run-current-case">
            <span>${active ? "正在处理" : "队列状态"}</span>
            <strong>${escapeHtml(active?.case?.case_id || run.status || "-")}</strong>
            <p>${escapeHtml(currentCaseText(active, preview))}</p>
        </div>
    `;
}

function progressSegment(segment, total) {
    if (!segment.count || !total) {
        return "";
    }
    const width = Math.max(2, (segment.count / total) * 100);
    return `<span class="experiment-progress-segment ${segment.className}" style="width: ${width}%;" title="${escapeAttr(`${segment.label} ${segment.count}`)}"></span>`;
}

function activeSubmission(run) {
    const submissions = run.submissions || [];
    return submissions.find((item) => item.status === "running")
        || submissions.find((item) => ["queued", "submitted"].includes(item.status))
        || submissions.find((item) => item.status === "error")
        || submissions[0]
        || null;
}

function currentCaseText(submission, preview) {
    if (!submission) {
        return `${preview.prompt_variants?.length || 0} prompt variants, ${preview.lora_combos?.length || 0} LoRA combos`;
    }
    const caseData = submission.case || {};
    return [
        caseData.lora_combo_label || "LoRA combo",
        `strength ${caseData.strength ?? "-"}`,
        `seed ${caseData.seed ?? "-"}`,
        submission.prompt_id ? `prompt ${submission.prompt_id}` : submission.status,
    ].filter(Boolean).join(" · ");
}

function isLiveRun(run) {
    return ["submitting", "queued", "running"].includes(run?.status);
}

function restartPolling() {
    stopPolling();
    if (isLiveRun(state.selectedRun) && !document.hidden) {
        schedulePoll();
    }
}

function schedulePoll(delay = 3000) {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = window.setTimeout(pollSelectedRun, delay);
}

async function pollSelectedRun() {
    if (!isLiveRun(state.selectedRun) || state.isPolling || document.hidden) {
        return;
    }
    state.isPolling = true;
    try {
        const result = await refreshExperimentRun(state.selectedRun.run_id);
        state.selectedRun = result.run;
        await loadRuns();
        renderRun();
    } catch (error) {
        showToast(error.message, true);
    } finally {
        state.isPolling = false;
        if (isLiveRun(state.selectedRun) && !document.hidden) {
            schedulePoll();
        }
    }
}

function stopPolling() {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = 0;
}

function renderResultGrid(run) {
    const preview = run.preview || {};
    const submissions = run.submissions || [];
    els.resultGrid.replaceChildren();
    if (!submissions.length) {
        els.resultGrid.innerHTML = `<div class="empty"><strong>还没有 case</strong><span>提交开始后这里会直接显示队列和结果卡片。</span></div>`;
        return;
    }
    const byVariant = groupBy(submissions, (item) => caseForSubmission(item).prompt_variant_id || "unknown");
    const variants = preview.prompt_variants?.length
        ? preview.prompt_variants
        : [{ id: "unknown", label: "Prompt variant", positive: "" }];
    for (const variant of variants) {
        const variantSubmissions = byVariant.get(variant.id) || [];
        if (!variantSubmissions.length) {
            continue;
        }
        const section = document.createElement("section");
        section.className = "result-section";
        section.innerHTML = `
            <div class="result-section-head">
                <div>
                    <h2>${escapeHtml(variant.label || variant.id)}</h2>
                    <p>${escapeHtml(compact(variant.positive, 240))}</p>
                </div>
            </div>
        `;
        const grid = document.createElement("div");
        grid.className = "result-cards";
        for (const submission of variantSubmissions) {
            grid.append(resultCard(submission));
        }
        section.append(grid);
        els.resultGrid.append(section);
    }
}

function resultCard(submission) {
    const card = document.createElement("button");
    const caseData = caseForSubmission(submission);
    const imageUrl = submissionImageUrl(submission);
    const progress = submissionProgress(submission);
    const errorMessage = submissionError(submission);
    const isCompletedImage = Boolean(imageUrl && submission.status === "completed");
    card.className = "result-card";
    card.dataset.status = submission.status || "submitted";
    card.type = "button";
    card.addEventListener("click", () => openResultDialog(submission));
    const preview = document.createElement("div");
    preview.className = "result-preview";
    if (imageUrl && progress >= 100 && submission.status !== "error") {
        const img = document.createElement("img");
        img.loading = "eager";
        img.src = imageUrl;
        img.alt = caseData.case_id || "result";
        preview.append(img);
    } else {
        const placeholder = document.createElement("div");
        placeholder.className = "result-placeholder";
        placeholder.textContent = submission.status || "submitted";
        preview.append(placeholder);
    }
    if (!isCompletedImage) {
        const meter = document.createElement("div");
        meter.className = "result-card-progress";
        meter.setAttribute("aria-label", `Progress ${progress}%`);
        meter.innerHTML = `<span style="width: ${progress}%"></span>`;
        preview.append(meter);
    }
    if (errorMessage) {
        const bubble = document.createElement("div");
        bubble.className = "result-error-bubble";
        bubble.textContent = errorMessage;
        preview.append(bubble);
    }
    card.append(preview);
    const body = document.createElement("div");
    body.className = "result-card-body";
    body.innerHTML = `
        <strong>${escapeHtml(caseData.lora_combo_label || "LoRA combo")}</strong>
        <span>strength ${escapeHtml(String(caseData.strength ?? "-"))} · seed ${escapeHtml(String(caseData.seed ?? "-"))}</span>
        ${isCompletedImage ? "" : `<span>${escapeHtml(statusLabel(submission.status))} · ${progress}%</span>`}
    `;
    card.append(body);
    return card;
}

function openResultDialog(submission) {
    const caseData = caseForSubmission(submission);
    const imageUrl = submissionImageUrl(submission);
    els.resultTitle.textContent = caseData.case_id || "Result";
    els.resultSubtitle.textContent = [
        caseData.prompt_variant_label || caseData.prompt_variant_id || "Prompt variant",
        caseData.lora_combo_label || "LoRA combo",
        `strength ${caseData.strength ?? "-"}`,
        `seed ${caseData.seed ?? "-"}`,
    ].join(" · ");
    els.resultBody.innerHTML = `
        ${imageUrl ? `<img class="detail-image" src="${escapeAttr(imageUrl)}" alt="">` : `<div class="empty"><strong>${escapeHtml(submission.status || "No output yet")}</strong><span>${escapeHtml(submissionError(submission) || "Refresh after ComfyUI completes the prompt.")}</span></div>`}
        ${caseParameterOverview(caseData, submission)}
        <div class="detail-section"><h3>Positive prompt</h3><p>${escapeHtml(caseData.prompt?.positive || "")}</p></div>
        <div class="detail-section"><h3>Negative prompt</h3><p>${escapeHtml(caseData.prompt?.negative || "")}</p></div>
    `;
    els.resultDialog.hidden = false;
    document.body.classList.add("dialog-open");
}

function caseForSubmission(submission) {
    if (submission.case && Object.keys(submission.case).length) {
        return submission.case;
    }
    return (state.selectedRun?.preview?.cases || []).find((item) => item.case_id === submission.case_id) || {};
}

function caseParameterOverview(caseData, submission) {
    const generation = caseData.generation || {};
    const models = caseData.models || {};
    const loras = models.loras || [];
    const rows = [
        ["checkpoint", models.checkpoint],
        ["seed", generation.seed ?? caseData.seed],
        ["steps", generation.steps],
        ["cfg", generation.cfg],
        ["sampler", generation.sampler],
        ["scheduler", generation.scheduler],
        ["denoise", generation.denoise],
        ["size", generation.width && generation.height ? `${generation.width}×${generation.height}` : ""],
        ["clip skip", generation.clip_skip],
        ["LoRA", loras.map((item) => `${item.name} ${item.strength}`).join(", ")],
    ].filter(([, value]) => value !== "" && value !== null && value !== undefined);
    return `
        <div class="detail-section detail-section-compact">
            <h3>Workflow parameters</h3>
            <div class="detail-kv-grid">
                ${rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd></div>`).join("")}
            </div>
        </div>
    `;
}

function closeResultDialog() {
    els.resultDialog.hidden = true;
    document.body.classList.remove("dialog-open");
}

function submissionImageUrl(submission) {
    const output = (submission.outputs || [])[0];
    return output?.url
        || output?.image_url
        || output?.path
        || submission.output_images?.[0]
        || submission.image_urls?.[0]
        || submission.result?.images?.[0]
        || "";
}

function submissionProgress(submission) {
    if (typeof submission.progress === "number") {
        return clampProgress(submission.progress);
    }
    if (submission.status === "completed") {
        return 100;
    }
    if (submission.status === "error") {
        return clampProgress(submission.percent ?? 100);
    }
    if (submission.status === "running") {
        return clampProgress(submission.percent ?? 55);
    }
    if (["queued", "submitted"].includes(submission.status)) {
        return clampProgress(submission.percent ?? 18);
    }
    return 0;
}

function clampProgress(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
        return 0;
    }
    return Math.max(0, Math.min(100, Math.round(number)));
}

function submissionError(submission) {
    if (submission.status !== "error") {
        return "";
    }
    return submission.error
        || submission.error_message
        || submission.result?.error
        || "Run failed. Open the card for details.";
}

function statusLabel(status) {
    if (status === "completed") {
        return "completed";
    }
    if (status === "error") {
        return "error";
    }
    if (status === "running") {
        return "running";
    }
    if (status === "queued" || status === "submitted") {
        return "queued";
    }
    return status || "pending";
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
