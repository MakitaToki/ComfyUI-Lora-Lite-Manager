import { collectionImageUrl, fetchArtworks } from "./collection_api.js";
import { fetchLoras, previewUrl } from "./api.js";
import { createExperimentRun, fetchExperimentRun, refreshExperimentRun, submitExperimentRunStep, previewExperiment } from "./experiment_api.js";

const FIXED_LORA_STRENGTH = 1;

const state = {
    artworks: [],
    loraItems: [],
    pickerMode: "main",
    pickerQuery: "",
    main: null,
    refs: [],
    jsonExpanded: false,
    latestPreview: null,
    activeRunId: "",
    runPollTimer: 0,
    isPollingRun: false,
    loras: [
        { name: "Pvnk_styl2.safetensors", strengths: [FIXED_LORA_STRENGTH] },
    ],
};

const els = {
    summary: document.querySelector("#summary"),
    caseCount: document.querySelector("#caseCount"),
    chooseMainBtn: document.querySelector("#chooseMainBtn"),
    addRefBtn: document.querySelector("#addRefBtn"),
    mainSeedSlot: document.querySelector("#mainSeedSlot"),
    referenceList: document.querySelector("#referenceList"),
    loraRows: document.querySelector("#loraRows"),
    chooseLoraBtn: document.querySelector("#chooseLoraBtn"),
    loraForm: document.querySelector("#loraForm"),
    loraNameInput: document.querySelector("#loraNameInput"),
    loraStrengthInput: document.querySelector("#loraStrengthInput"),
    checkpointInput: document.querySelector("#checkpointInput"),
    stepsInput: document.querySelector("#stepsInput"),
    samplerInput: document.querySelector("#samplerInput"),
    schedulerInput: document.querySelector("#schedulerInput"),
    widthInput: document.querySelector("#widthInput"),
    heightInput: document.querySelector("#heightInput"),
    seedsInput: document.querySelector("#seedsInput"),
    promptModeInput: document.querySelector("#promptModeInput"),
    matrixSummary: document.querySelector("#matrixSummary"),
    experimentPreviewSummary: document.querySelector("#experimentPreviewSummary"),
    runProgressPanel: document.querySelector("#runProgressPanel"),
    runProgressTitle: document.querySelector("#runProgressTitle"),
    runProgressMessage: document.querySelector("#runProgressMessage"),
    runProgressBar: document.querySelector("#runProgressBar"),
    runProgressStats: document.querySelector("#runProgressStats"),
    runDiagnostics: document.querySelector("#runDiagnostics"),
    openRunBtn: document.querySelector("#openRunBtn"),
    toggleJsonBtn: document.querySelector("#toggleJsonBtn"),
    recipePreview: document.querySelector("#recipePreview"),
    previewExperimentBtn: document.querySelector("#previewExperimentBtn"),
    runExperimentBtn: document.querySelector("#runExperimentBtn"),
    exportRecipeBtn: document.querySelector("#exportRecipeBtn"),
    pickerDialog: document.querySelector("#pickerDialog"),
    pickerTitle: document.querySelector("#pickerTitle"),
    pickerHint: document.querySelector("#pickerHint"),
    closePickerBtn: document.querySelector("#closePickerBtn"),
    pickerSearch: document.querySelector("#pickerSearch"),
    pickerFilter: document.querySelector("#pickerFilter"),
    pickerGrid: document.querySelector("#pickerGrid"),
    toast: document.querySelector("#toast"),
};

init();

async function init() {
    bindEvents();
    renderAll();
    await Promise.all([loadArtworks(), loadLoras()]);
    await restoreRecipeFromRunParam();
}

function bindEvents() {
    els.chooseMainBtn.addEventListener("click", () => openPicker("main"));
    els.addRefBtn.addEventListener("click", () => openPicker("ref"));
    els.chooseLoraBtn.addEventListener("click", () => openPicker("lora"));
    els.closePickerBtn.addEventListener("click", closePicker);
    els.pickerDialog.addEventListener("click", (event) => {
        if (event.target === els.pickerDialog) {
            closePicker();
        }
    });
    els.pickerSearch.addEventListener("input", () => {
        state.pickerQuery = els.pickerSearch.value.trim().toLowerCase();
        renderPicker();
    });
    els.pickerFilter.addEventListener("change", () => {
        renderPicker();
    });
    els.pickerGrid.addEventListener("wheel", stopScrollBleed, { passive: false });
    els.loraForm.addEventListener("submit", addLora);
    for (const input of [els.checkpointInput, els.stepsInput, els.samplerInput, els.schedulerInput, els.widthInput, els.heightInput, els.seedsInput, els.promptModeInput]) {
        input.addEventListener("input", renderPreview);
    }
    els.promptModeInput.addEventListener("change", renderPreview);
    if (els.loraStrengthInput) {
        els.loraStrengthInput.value = String(FIXED_LORA_STRENGTH);
    }
    els.previewExperimentBtn.addEventListener("click", handlePreviewExperiment);
    els.runExperimentBtn.addEventListener("click", handleRunExperiment);
    els.toggleJsonBtn.addEventListener("click", toggleJsonPreview);
    els.exportRecipeBtn.addEventListener("click", () => {
        setJsonExpanded(true);
        renderJsonPreview(state.latestPreview || buildRecipe());
        document.getElementById("experiments")?.scrollIntoView({ behavior: "smooth", block: "start" });
        showToast("完整 JSON 已展开");
    });
}

function stopScrollBleed(event) {
    const target = els.pickerGrid;
    const maxScroll = target.scrollHeight - target.clientHeight;
    if (maxScroll <= 0) {
        event.preventDefault();
        return;
    }
    const atTop = target.scrollTop <= 0;
    const atBottom = target.scrollTop >= maxScroll - 1;
    if ((event.deltaY < 0 && atTop) || (event.deltaY > 0 && atBottom)) {
        event.preventDefault();
    }
    event.stopPropagation();
}

async function loadArtworks() {
    setSummary("正在读取作品集...");
    try {
        const result = await fetchArtworks({ sort: "newest", limit: 120 });
        state.artworks = result.items || [];
        setSummary(`已读取 ${state.artworks.length} 张素材`);
        renderPicker();
    } catch (error) {
        showToast(error.message, true);
        setSummary("作品集读取失败");
    }
}

async function loadLoras() {
    try {
        const result = await fetchLoras();
        state.loraItems = result.items || [];
        renderPicker();
    } catch (error) {
        showToast(`LoRA 列表读取失败：${error.message}`, true);
    }
}

async function restoreRecipeFromRunParam() {
    const runId = new URLSearchParams(window.location.search).get("run_id");
    if (!runId) {
        return;
    }
    try {
        const result = await fetchExperimentRun(runId);
        applyRecipe(result.run?.recipe || {});
        window.history.replaceState(null, "", "/recipe-lite");
        showToast(`已恢复历史配方：${runId}`);
    } catch (error) {
        showToast(`恢复历史配方失败：${error.message}`, true);
    }
}

function applyRecipe(recipe) {
    state.main = recipe.main_artwork ? recipeArtwork(recipe.main_artwork) : null;
    state.refs = (Array.isArray(recipe.visual_references) ? recipe.visual_references : [])
        .map((item) => ({ ...recipeArtwork(item), usage: item.usage || "参考构图" }));
    state.loras = (Array.isArray(recipe.lora_matrix) ? recipe.lora_matrix : [])
        .map((item) => ({
            name: item.name || "",
            strengths: fixedStrengths(),
            notes: item.notes || "",
            trigger_words: Array.isArray(item.trigger_words) ? item.trigger_words : [],
            base_model: item.base_model || "",
            source_url: item.source_url || "",
            download_url: item.download_url || "",
        }))
        .filter((item) => item.name);
    const generation = recipe.generation || {};
    els.checkpointInput.value = generation.checkpoint || "";
    els.stepsInput.value = generation.steps || 22;
    els.samplerInput.value = generation.sampler || "euler_ancestral";
    els.schedulerInput.value = generation.scheduler || "normal";
    els.widthInput.value = generation.width || 832;
    els.heightInput.value = generation.height || 1216;
    els.seedsInput.value = (Array.isArray(recipe.seeds) ? recipe.seeds : []).join(", ") || "123456, 234567";
    els.promptModeInput.value = recipe.prompt_mode || "danbooru";
    renderAll();
}

function recipeArtwork(ref) {
    const existing = state.artworks.find((item) => item.id === ref.id);
    if (existing) {
        return existing;
    }
    return {
        ...ref,
        meta: { title: ref.title || ref.id || "" },
        user_notes: ref.title || ref.id || "",
        raw_tags: [],
        visual_structure: {},
        design_language: {},
        positive_prompt: ref.positive_prompt || "",
        negative_prompt: ref.negative_prompt || "",
    };
}

function openPicker(mode) {
    state.pickerMode = mode;
    els.pickerSearch.value = "";
    state.pickerQuery = "";
    els.pickerFilter.hidden = mode === "lora";
    els.pickerFilter.value = mode === "main" ? "main" : "all";
    els.pickerTitle.textContent = mode === "main" ? "选择主素材" : mode === "lora" ? "选择 LoRA" : "添加参考素材";
    els.pickerHint.textContent = mode === "main"
        ? "主素材需要有可直接送进 ComfyUI 的提示词。"
        : mode === "lora"
            ? "这里显示 LoRA 管理页里的备注和触发词，用它们判断风格是否适合本次实验。"
            : "参考素材会作为构图、色彩、氛围或设计语言备注保存。";
    els.pickerDialog.hidden = false;
    document.body.classList.add("dialog-open");
    renderPicker();
}

function closePicker() {
    els.pickerDialog.hidden = true;
    document.body.classList.remove("dialog-open");
}

function renderPicker() {
    if (!els.pickerGrid) {
        return;
    }
    if (state.pickerMode === "lora") {
        renderLoraPicker();
        return;
    }

    const filter = els.pickerFilter.value;
    const items = state.artworks.filter((item) => {
        if (filter === "main" && !isDirectlyGeneratable(item)) {
            return false;
        }
        if (!state.pickerQuery) {
            return true;
        }
        return searchText(item).includes(state.pickerQuery);
    });

    els.pickerGrid.replaceChildren();
    for (const item of items) {
        const card = document.createElement("button");
        card.className = "picker-item";
        card.type = "button";
        card.addEventListener("click", () => chooseArtwork(item));

        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = collectionImageUrl(item.preview_path || item.image_url);
        img.alt = titleOf(item);
        card.append(img);

        const body = document.createElement("div");
        body.append(textEl("strong", titleOf(item)));
        body.append(textEl("span", isDirectlyGeneratable(item) ? "可直接生成" : "需要整理提示词"));
        body.append(textEl("p", descriptionOf(item)));
        body.append(promptSummaryEl(item));
        body.append(referenceSummaryEl(item));
        card.append(body);
        els.pickerGrid.append(card);
    }

    if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "details-empty";
        empty.textContent = filter === "main" ? "没有找到可直接生成的素材。" : "没有找到素材。";
        els.pickerGrid.append(empty);
    }
}

function renderLoraPicker() {
    const items = state.loraItems.filter((item) => {
        if (!state.pickerQuery) {
            return true;
        }
        return loraSearchText(item).includes(state.pickerQuery);
    });

    els.pickerGrid.replaceChildren();
    for (const item of items) {
        const card = document.createElement("button");
        card.className = "picker-item lora-picker-item";
        card.type = "button";
        card.addEventListener("click", () => chooseLora(item));

        const image = previewUrl(item.preview_path);
        if (image) {
            const img = document.createElement("img");
            img.loading = "lazy";
            img.src = image;
            img.alt = item.name;
            card.append(img);
        } else {
            const thumb = document.createElement("div");
            thumb.className = "lora-picker-thumb";
            thumb.textContent = "LoRA";
            card.append(thumb);
        }

        const body = document.createElement("div");
        body.append(textEl("strong", item.name));
        body.append(textEl("span", loraNotes(item) || "还没有风格备注"));
        body.append(textEl("p", loraDescription(item)));
        card.append(body);
        els.pickerGrid.append(card);
    }

    if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "details-empty";
        empty.textContent = "没有找到 LoRA。";
        els.pickerGrid.append(empty);
    }
}

function chooseArtwork(item) {
    if (state.pickerMode === "main") {
        state.main = item;
    } else if (!state.refs.some((ref) => ref.id === item.id)) {
        state.refs.push({ ...item, usage: "参考构图" });
    }
    closePicker();
    renderAll();
}

function chooseLora(item) {
    if (!state.loras.some((lora) => lora.name === item.file_name)) {
        state.loras.push({
            name: item.file_name,
            strengths: fixedStrengths(),
            notes: loraNotes(item),
            trigger_words: loraTriggerWords(item),
            base_model: item.base_model || "",
            source_url: loraLinks(item).modelPage,
            download_url: loraLinks(item).download,
        });
    }
    closePicker();
    renderAll();
}

function renderAll() {
    renderMain();
    renderRefs();
    renderLoras();
    renderPreview();
}

function renderMain() {
    const item = state.main;
    if (!item) {
        els.mainSeedSlot.className = "selected-slot empty-slot";
        els.mainSeedSlot.innerHTML = "<strong>还没有选择主素材</strong><span>请选择一张 Civitai / AI 生成作品作为提示词来源。</span>";
        return;
    }
    els.mainSeedSlot.className = "selected-slot artwork-slot";
    els.mainSeedSlot.innerHTML = artworkSlotHtml(item, "主素材", true);
    els.mainSeedSlot.querySelector("button").addEventListener("click", () => {
        state.main = null;
        renderAll();
    });
}

function renderRefs() {
    els.referenceList.replaceChildren();
    if (!state.refs.length) {
        const empty = document.createElement("div");
        empty.className = "selected-slot empty-slot";
        empty.innerHTML = "<strong>没有参考素材</strong><span>可以稍后添加构图、色彩、氛围或设计语言参考。</span>";
        els.referenceList.append(empty);
        return;
    }

    for (const ref of state.refs) {
        const slot = document.createElement("div");
        slot.className = "selected-slot artwork-slot";
        slot.innerHTML = artworkSlotHtml(ref, "参考素材", true);

        const usage = document.createElement("select");
        usage.className = "usage-select";
        for (const label of ["参考构图", "参考色彩", "参考氛围", "参考角色/主体", "仅备注"]) {
            const option = document.createElement("option");
            option.value = label;
            option.textContent = label;
            option.selected = ref.usage === label;
            usage.append(option);
        }
        usage.addEventListener("change", () => {
            ref.usage = usage.value;
            renderPreview();
        });
        slot.querySelector(".slot-text").append(usage);
        slot.querySelector("button").addEventListener("click", () => {
            state.refs = state.refs.filter((item) => item.id !== ref.id);
            renderAll();
        });
        els.referenceList.append(slot);
    }
}

function renderLoras() {
    els.loraRows.replaceChildren();
    for (const [index, lora] of state.loras.entries()) {
        const row = document.createElement("div");
        row.className = "lora-row";
        row.innerHTML = `
            <div class="lora-row-main">
                <strong>${escapeHtml(lora.name)}</strong>
                ${lora.notes ? `<p>${escapeHtml(lora.notes)}</p>` : '<p class="muted-text">还没有风格备注，可以去 LoRA 管理页补上。</p>'}
                ${lora.trigger_words?.length ? `<span>触发词：${escapeHtml(lora.trigger_words.slice(0, 8).join(", "))}</span>` : ""}
            </div>
            <div class="strength-chips">
                ${lora.strengths.map((value) => `<span>${value}</span>`).join("")}
            </div>
            <button class="icon-button" type="button" aria-label="移除">x</button>
        `;
        row.querySelector("button").addEventListener("click", () => {
            state.loras.splice(index, 1);
            renderAll();
        });
        els.loraRows.append(row);
    }
}

function addLora(event) {
    event.preventDefault();
    const name = els.loraNameInput.value.trim();
    if (!name) {
        showToast("请填写 LoRA 文件名", true);
        return;
    }
    state.loras.push({ name, strengths: fixedStrengths() });
    els.loraNameInput.value = "";
    if (els.loraStrengthInput) {
        els.loraStrengthInput.value = String(FIXED_LORA_STRENGTH);
    }
    renderAll();
}

function renderPreview() {
    state.latestPreview = null;
    const recipe = buildRecipe();
    const comboCount = 1 + state.loras.length + (state.loras.length * (state.loras.length - 1)) / 2;
    const strengthCount = Math.max(1, uniqueStrengths().length);
    const seedCount = Math.max(1, recipe.seeds.length);
    const variantCount = state.main ? 1 + state.refs.length : 0;
    const caseCount = state.main ? variantCount * comboCount * strengthCount * seedCount : 0;
    els.caseCount.textContent = `${caseCount} 张`;
    els.matrixSummary.textContent = state.main
        ? `${variantCount} prompt variants × ${comboCount} LoRA combos × ${strengthCount} strengths × ${seedCount} seeds = ${caseCount} images`
        : "先选择主素材，再展开实验数量。";
    renderSummaryCards({
        total: caseCount,
        promptVariants: variantCount,
        loraCombos: comboCount,
        strengths: strengthCount,
        seeds: seedCount,
        checkpoint: recipe.generation.checkpoint || "-",
        sampler: samplerSummary(recipe.generation.sampler, recipe.generation.scheduler),
        size: `${recipe.generation.width} × ${recipe.generation.height}`,
    });
    if (state.jsonExpanded) {
        renderJsonPreview(recipe);
    }
}

async function handlePreviewExperiment() {
    try {
        const result = await previewExperiment(buildRecipe());
        state.latestPreview = result.preview;
        renderExperimentPreview(result.preview);
        if (state.jsonExpanded) {
            renderJsonPreview(result.preview);
        }
        showToast("Experiment preview updated");
    } catch (error) {
        showToast(error.message, true);
    }
}

async function handleRunExperiment() {
    if (!state.main) {
        showToast("Select a main artwork first.", true);
        return;
    }
    els.runExperimentBtn.disabled = true;
    els.previewExperimentBtn.disabled = true;
    els.runExperimentBtn.textContent = "Submitting...";
    setRunProgress(null, "prepare", "创建 run", "正在创建实验记录，随后会生成 workflow 并提交到 ComfyUI /prompt。");
    try {
        const result = await createExperimentRun(buildRecipe(), { submit: false });
        let run = result.run;
        state.activeRunId = run.run_id;
        setRunProgress(run, "submit", "提交 ComfyUI /prompt", "已创建 run，正在为每个 case 生成 workflow 并提交。");

        while (hasPendingSubmissions(run)) {
            const step = await submitExperimentRunStep(run.run_id, { batchSize: 1 });
            run = step.run;
            const pending = hasPendingSubmissions(run);
            const stats = runStats(run);
            const nextStage = stats.error ? "error" : pending ? "submit" : "queue";
            setRunProgress(run, nextStage, pending ? "提交 ComfyUI /prompt" : "等待 ComfyUI 队列 / 执行", latestRunMessage(run));
        }

        const refreshed = await refreshExperimentRun(run.run_id).catch(() => ({ run }));
        run = refreshed.run || run;
        const stats = runStats(run);
        const finalStage = stats.error ? "error" : run.status === "completed" ? "done" : "queue";
        const finalTitle = stats.error ? "部分 case 失败" : run.status === "completed" ? "已完成" : "等待 ComfyUI 队列 / 执行";
        setRunProgress(run, finalStage, finalTitle, latestRunMessage(run));
        startRecipeRunPolling(run);
        showToast(`Experiment run created: ${run.run_id}`);
    } catch (error) {
        setRunProgress(null, "error", "创建 run 失败", error.message, { error });
        showToast(error.message, true);
    } finally {
        els.runExperimentBtn.disabled = false;
        els.previewExperimentBtn.disabled = false;
        els.runExperimentBtn.textContent = "Run experiment";
    }
}

function renderExperimentPreview(preview) {
    const summary = preview.summary || {};
    renderSummaryCards({
        total: summary.total || 0,
        promptVariants: preview.prompt_variants?.length || 0,
        loraCombos: preview.lora_combos?.length || 0,
        strengths: preview.strengths?.length || 0,
        seeds: preview.seeds?.length || 0,
        checkpoint: preview.cases?.[0]?.models?.checkpoint || els.checkpointInput.value.trim() || "-",
        sampler: preview.cases?.[0]?.generation ? samplerSummary(preview.cases[0].generation.sampler, preview.cases[0].generation.scheduler) : samplerSummary(els.samplerInput.value, els.schedulerInput.value),
        size: preview.cases?.[0]?.generation ? `${preview.cases[0].generation.width} × ${preview.cases[0].generation.height}` : `${els.widthInput.value} × ${els.heightInput.value}`,
        warning: summary.warning,
    });
}

function renderSummaryCards(summary) {
    els.experimentPreviewSummary.hidden = false;
    const checkpoint = summary.checkpoint || "-";
    const sampler = summary.sampler || "-";
    const size = summary.size || "-";
    els.experimentPreviewSummary.innerHTML = `
        <div class="summary-card"><strong>${summary.total || 0}</strong><span>images</span></div>
        <div class="summary-card"><strong>${summary.promptVariants || 0}</strong><span>prompt variants</span></div>
        <div class="summary-card"><strong>${summary.loraCombos || 0}</strong><span>LoRA combos</span></div>
        <div class="summary-card"><strong>${summary.strengths || 0}</strong><span>strengths</span></div>
        <div class="summary-card"><strong>${summary.seeds || 0}</strong><span>seeds</span></div>
        <div class="summary-card summary-card-wide" title="${escapeAttr(checkpoint)}"><strong>${escapeHtml(checkpoint)}</strong><span>checkpoint</span></div>
        <div class="summary-card summary-card-wide" title="${escapeAttr(sampler)}"><strong>${escapeHtml(sampler)}</strong><span>sampler</span></div>
        <div class="summary-card summary-card-size"><strong>${escapeHtml(size)}</strong><span>size</span></div>
        ${summary.warning ? `<p>${escapeHtml(summary.warning)}</p>` : ""}
    `;
}

function samplerSummary(sampler, scheduler) {
    const samplerText = String(sampler || "").trim();
    const schedulerText = String(scheduler || "").trim();
    if (samplerText && schedulerText) {
        return `${samplerText} / ${schedulerText}`;
    }
    return samplerText || schedulerText || "-";
}

function toggleJsonPreview() {
    setJsonExpanded(!state.jsonExpanded);
    if (state.jsonExpanded) {
        renderJsonPreview(state.latestPreview || buildRecipe());
    }
}

function setJsonExpanded(expanded) {
    state.jsonExpanded = expanded;
    els.recipePreview.hidden = !expanded;
    els.toggleJsonBtn.textContent = expanded ? "收起完整 JSON" : "查看完整 JSON";
}

function renderJsonPreview(value) {
    els.recipePreview.textContent = JSON.stringify(value, null, 2);
}

function hasPendingSubmissions(run) {
    return (run?.submissions || []).some((item) => item.status === "pending");
}

function setRunProgress(run, stage, title, message, options = {}) {
    els.runProgressPanel.hidden = false;
    els.runProgressTitle.textContent = title;
    els.runProgressMessage.textContent = message || "";
    els.runProgressPanel.dataset.stage = stage;
    const stats = runStats(run);
    const percent = stats.total ? Math.round(((stats.queued + stats.running + stats.completed + stats.error) / stats.total) * 100) : 0;
    els.runProgressBar.style.width = `${percent}%`;
    els.runProgressStats.innerHTML = `
        <span>总数 ${stats.total}</span>
        <span>待提交 ${stats.pending}</span>
        <span>已进队列 ${stats.queued}</span>
        <span>执行中 ${stats.running}</span>
        <span>完成 ${stats.completed}</span>
        <span>失败 ${stats.error}</span>
    `;
    els.openRunBtn.hidden = !run?.run_id;
    if (run?.run_id) {
        els.openRunBtn.href = `/experiments-lite?run_id=${encodeURIComponent(run.run_id)}`;
    }
    renderRunDiagnostics(run, options.error);
}

function runStats(run) {
    const submissions = run?.submissions || [];
    const total = run?.preview?.summary?.total || submissions.length || 0;
    return {
        total,
        pending: submissions.filter((item) => item.status === "pending").length,
        queued: submissions.filter((item) => ["queued", "submitted"].includes(item.status)).length,
        running: submissions.filter((item) => item.status === "running").length,
        completed: submissions.filter((item) => item.status === "completed").length,
        error: submissions.filter((item) => item.status === "error").length,
    };
}

function latestRunMessage(run) {
    const stats = runStats(run);
    if (stats.error) {
        const failed = (run.submissions || []).find((item) => item.status === "error");
        return `有 ${stats.error} 个 case 失败，先看下面的问题详情。${failed?.error_message || failed?.error || ""}`;
    }
    if (stats.pending) {
        return `还剩 ${stats.pending} 个 case 等待提交。`;
    }
    if (stats.running) {
        return `${stats.running} 个 case 正在 ComfyUI 执行，${stats.completed} 个已完成。`;
    }
    if (run?.status === "completed") {
        return "ComfyUI 已生成完成。";
    }
    return "所有 case 已提交到 ComfyUI，正在等待队列或执行。";
}

function startRecipeRunPolling(run) {
    window.clearTimeout(state.runPollTimer);
    state.activeRunId = run?.run_id || "";
    if (!isLiveRun(run)) {
        return;
    }
    state.runPollTimer = window.setTimeout(pollRecipeRun, 3000);
}

async function pollRecipeRun() {
    if (!state.activeRunId || state.isPollingRun) {
        return;
    }
    state.isPollingRun = true;
    try {
        const result = await refreshExperimentRun(state.activeRunId);
        const run = result.run;
        const stats = runStats(run);
        const stage = stats.error ? "error" : run.status === "completed" ? "done" : stats.running ? "queue" : "queue";
        const title = stats.error ? "部分 case 失败" : run.status === "completed" ? "已完成" : "等待 ComfyUI 队列 / 执行";
        setRunProgress(run, stage, title, latestRunMessage(run));
        if (isLiveRun(run)) {
            state.runPollTimer = window.setTimeout(pollRecipeRun, 3000);
        }
    } catch (error) {
        showToast(error.message, true);
        state.runPollTimer = window.setTimeout(pollRecipeRun, 5000);
    } finally {
        state.isPollingRun = false;
    }
}

function isLiveRun(run) {
    return ["submitting", "queued", "running"].includes(run?.status);
}

function renderRunDiagnostics(run, generalError) {
    const failures = failedSubmissions(run);
    if (!failures.length && !generalError) {
        els.runDiagnostics.hidden = true;
        els.runDiagnostics.replaceChildren();
        return;
    }

    els.runDiagnostics.hidden = false;
    const failureItems = failures.slice(0, 5).map((submission) => {
        const caseData = caseForSubmission(run, submission);
        return `
            <details class="diagnostic-item">
                <summary>
                    <strong>${escapeHtml(submission.case_id || caseData.case_id || "case")}</strong>
                    <span>${escapeHtml(stageLabel(submission.stage))} · ${escapeHtml(errorTypeHint(submission))}</span>
                </summary>
                <dl>
                    <div><dt>Prompt</dt><dd>${escapeHtml(caseData.prompt_variant_label || caseData.prompt_variant_id || "-")}</dd></div>
                    <div><dt>LoRA</dt><dd>${escapeHtml(caseData.lora_combo_label || caseData.lora_combo_id || "-")}</dd></div>
                    <div><dt>Strength</dt><dd>${escapeHtml(String(caseData.strength ?? "-"))}</dd></div>
                    <div><dt>Seed</dt><dd>${escapeHtml(String(caseData.seed ?? "-"))}</dd></div>
                    <div><dt>原因</dt><dd>${escapeHtml(submission.error_message || submission.error || "-")}</dd></div>
                </dl>
                <pre>${escapeHtml(submission.error_detail || submission.error || "")}</pre>
            </details>
        `;
    }).join("");

    const general = generalError ? `
        <details class="diagnostic-item" open>
            <summary><strong>创建 run 失败</strong><span>${escapeHtml(errorTypeHint({ error_detail: generalError.message, error: generalError.message }))}</span></summary>
            <pre>${escapeHtml(generalError.message || String(generalError))}</pre>
        </details>
    ` : "";
    const more = failures.length > 5 ? `<p class="diagnostic-more">还有 ${failures.length - 5} 个失败 case，可打开实验结果页查看。</p>` : "";
    els.runDiagnostics.innerHTML = `
        <div class="diagnostic-head">
            <div>
                <h4>问题详情</h4>
                <p>${escapeHtml(diagnosticSummary(run, generalError))}</p>
            </div>
        </div>
        ${general}
        ${failureItems}
        ${more}
        <div class="diagnostic-actions">
            ${run?.run_id ? `<a class="button secondary" href="/experiments-lite?run_id=${encodeURIComponent(run.run_id)}">打开实验结果页</a>` : ""}
            <button id="copyDiagnosticsBtn" class="button secondary" type="button">复制诊断信息</button>
        </div>
    `;
    document.querySelector("#copyDiagnosticsBtn")?.addEventListener("click", () => copyDiagnostics(run, generalError));
}

function failedSubmissions(run) {
    return (run?.submissions || []).filter((item) => item.status === "error");
}

function caseForSubmission(run, submission) {
    return (run?.preview?.cases || []).find((item) => item.case_id === submission.case_id) || {};
}

function stageLabel(stage) {
    return {
        pending: "待提交",
        workflow: "生成 workflow",
        prompt: "提交 /prompt",
        queue: "ComfyUI 队列",
        history: "查询 history",
        completed: "已完成",
    }[stage] || "未知阶段";
}

function errorTypeHint(submission) {
    const type = submission.error_type || classifyErrorText(submission.error_detail || submission.error || "");
    return {
        connection: "检查 ComfyUI 是否运行、端口是否正确",
        comfyui_http: "ComfyUI 拒绝请求，检查 workflow、模型文件或节点输入",
        missing_prompt_id: "ComfyUI 响应异常，没有返回 prompt_id",
        workflow: "生成 workflow 失败，检查 case 参数和节点模板",
        history: "任务可能已提交，但结果查询失败",
        unknown: "未归类错误，查看原始错误",
    }[type] || "未归类错误，查看原始错误";
}

function classifyErrorText(value) {
    const text = String(value || "").toLowerCase();
    if (text.includes("prompt_id")) return "missing_prompt_id";
    if (text.includes("timed out") || text.includes("timeout") || text.includes("connection") || text.includes("refused") || text.includes("urlopen")) return "connection";
    if (text.includes("http") || text.includes("/prompt")) return "comfyui_http";
    return "unknown";
}

function diagnosticSummary(run, generalError) {
    if (generalError) {
        return "创建 run 或调用接口时失败，下面保留了原始错误。";
    }
    const stats = runStats(run);
    return `${stats.error} 个 case 失败。展开条目可以查看 case 参数和原始错误。`;
}

function copyDiagnostics(run, generalError) {
    const text = diagnosticText(run, generalError);
    navigator.clipboard?.writeText(text)
        .then(() => showToast("诊断信息已复制"))
        .catch(() => showToast("无法复制诊断信息", true));
}

function diagnosticText(run, generalError) {
    const stats = runStats(run);
    const lines = [
        `run_id: ${run?.run_id || "-"}`,
        `status: ${run?.status || "-"}`,
        `total: ${stats.total}, pending: ${stats.pending}, queued: ${stats.queued}, running: ${stats.running}, completed: ${stats.completed}, error: ${stats.error}`,
    ];
    if (generalError) {
        lines.push(`general_error: ${generalError.message || String(generalError)}`);
    }
    for (const submission of failedSubmissions(run)) {
        const caseData = caseForSubmission(run, submission);
        lines.push("");
        lines.push(`case: ${submission.case_id || caseData.case_id || "-"}`);
        lines.push(`stage: ${submission.stage || "-"}`);
        lines.push(`prompt: ${caseData.prompt_variant_label || caseData.prompt_variant_id || "-"}`);
        lines.push(`lora: ${caseData.lora_combo_label || caseData.lora_combo_id || "-"}`);
        lines.push(`strength: ${caseData.strength ?? "-"}`);
        lines.push(`seed: ${caseData.seed ?? "-"}`);
        lines.push(`message: ${submission.error_message || submission.error || "-"}`);
        lines.push(`detail: ${submission.error_detail || submission.error || "-"}`);
    }
    return lines.join("\n");
}

function buildRecipe() {
    return {
        recipe_id: "lora_strength_test",
        name: "LoRA 强度测试",
        main_artwork: state.main ? artworkRef(state.main) : null,
        visual_references: state.refs.map((item) => ({ ...artworkRef(item), usage: item.usage })),
        lora_matrix: state.loras.map((item) => ({
            name: item.name,
            strengths: fixedStrengths(),
            notes: item.notes || "",
            trigger_words: item.trigger_words || [],
            base_model: item.base_model || "",
            source_url: item.source_url || "",
            download_url: item.download_url || "",
        })),
        fixed_loras: fixedLorasForRecipe(),
        seeds: parseNumberList(els.seedsInput.value).map((value) => Math.trunc(value)),
        prompt_mode: els.promptModeInput.value,
        generation: {
            checkpoint: els.checkpointInput.value.trim(),
            steps: Number(els.stepsInput.value) || 22,
            sampler: els.samplerInput.value.trim() || "euler_ancestral",
            scheduler: els.schedulerInput.value.trim() || "normal",
            width: Number(els.widthInput.value) || 832,
            height: Number(els.heightInput.value) || 1216,
            source_artwork: {
                enabled: true,
                artwork_id: state.main?.id || "",
                apply_fields: ["cfg", "clip_skip", "denoise"],
                carry_fields: ["seed", "steps", "width", "height", "model", "model_hash", "hires", "token_merge"],
            },
        },
        prompt_policy: {
            main_artwork: "使用主素材的正向/负向提示词",
            visual_references: "仅作为备注保存，暂不直接进入 ComfyUI prompt",
        },
    };
}

function loraNotes(item) {
    return String(item.metadata?.notes || item.notes || "").trim();
}

function uniqueStrengths() {
    return fixedStrengths();
}

function fixedStrengths() {
    return [FIXED_LORA_STRENGTH];
}

function loraTriggerWords(item) {
    const metadata = item.metadata || {};
    const words = item.trigger_words || metadata.trigger_words || metadata.trained_words || [];
    return Array.isArray(words) ? words.map(String).filter(Boolean) : [];
}

function loraDescription(item) {
    const parts = [
        item.base_model,
        loraTriggerWords(item).slice(0, 6).join(", "),
        item.relative_path,
    ].filter(Boolean);
    return parts.join(" · ") || item.file_name || item.name;
}

function loraSearchText(item) {
    return [
        item.name,
        item.file_name,
        item.relative_path,
        item.base_model,
        loraNotes(item),
        ...loraTriggerWords(item),
    ].join(" ").toLowerCase();
}

function loraLinks(item) {
    const metadata = item.metadata || {};
    const civitai = item.civitai || metadata.civitai || {};
    const modelId = civitai.modelId || civitai.model?.id || "";
    const versionId = civitai.modelVersionId || civitai.version?.id || "";
    const fileDownload = civitai.file?.downloadUrl || "";
    return {
        modelPage: metadata.source_url || civitai.modelPageUrl || (modelId && versionId ? `https://civitai.com/models/${modelId}?modelVersionId=${versionId}` : ""),
        download: metadata.download_url || civitai.downloadUrl || fileDownload || (versionId ? `https://civitai.com/api/download/models/${versionId}` : ""),
    };
}

function fixedLorasForRecipe() {
    const denia = state.loraItems.find((item) => {
        const metadata = item.metadata || {};
        const civitai = item.civitai || metadata.civitai || {};
        const modelId = String(civitai.modelId || civitai.model?.id || metadata.model_id || "");
        const text = [
            item.name,
            item.file_name,
            item.relative_path,
            metadata.name,
            civitai.model?.name,
        ].join(" ").toLowerCase();
        return modelId === "2488372" || text.includes("denia") || text.includes("dania");
    });
    if (!denia) {
        return [];
    }
    return [
        {
            name: denia.file_name || denia.name,
            strength: 1.0,
            clipStrength: 1.0,
            role: "fixed_role_lora",
            applies_to: ["role", "subject", "subject+composition", "role+composition"],
            source_url: loraLinks(denia).modelPage || "https://civitai.com/models/2488372/denia-or-wuthering-waves",
        },
    ];
}

function artworkRef(item) {
    const ref = {
        id: item.id,
        title: titleOf(item),
        source: item.source,
        source_url: item.source_url,
        asset_type: item.asset_type,
        prompt_state: isDirectlyGeneratable(item) ? "可直接生成" : "需要整理提示词",
        prompts: {
            positive: String(item.positive_prompt || item.meta?.prompt || "").trim(),
            negative: String(item.negative_prompt || item.meta?.negativePrompt || "").trim(),
        },
    };
    const sourceGeneration = artworkSourceGeneration(item);
    if (sourceGeneration) {
        ref.source_generation = sourceGeneration;
    }
    return ref;
}

function artworkSlotHtml(item, badge, removable) {
    return `
        <img src="${escapeAttr(collectionImageUrl(item.preview_path || item.image_url))}" alt="">
        <div class="slot-text">
            <span>${escapeHtml(badge)} · ${isDirectlyGeneratable(item) ? "可直接生成" : "需要整理"}</span>
            <strong>${escapeHtml(titleOf(item))}</strong>
            ${promptSummaryHtml(item)}
            ${referenceSummaryHtml(item)}
        </div>
        ${removable ? '<button class="icon-button" type="button" aria-label="移除">x</button>' : ""}
    `;
}

function artworkSourceGeneration(item) {
    const generation = item.aigc_seed || item.meta?.generation || {};
    const raw = item.meta?.raw_generation || item.meta?.generation || generation;
    if (!generation || !Object.keys(generation).length) {
        return null;
    }
    const workflowFields = pruneEmpty({
        steps: intValue(generation.steps ?? item.meta?.steps),
        cfg: numberValue(generation.cfg_scale ?? item.meta?.cfgScale),
        sampler: stringValue(generation.sampler ?? item.meta?.sampler),
        scheduler: stringValue(generation.schedule_type ?? generation.scheduler ?? item.meta?.["Schedule type"]),
        seed: intValue(generation.seed ?? item.meta?.seed),
        clip_skip: intValue(generation.clip_skip ?? item.meta?.clipSkip),
        width: intValue(generation.width ?? item.meta?.width),
        height: intValue(generation.height ?? item.meta?.height),
        denoise: numberValue(generation.denoising_strength ?? item.meta?.["Denoising strength"]),
    });
    const carryFields = pruneEmpty({
        model: stringValue(generation.model ?? item.meta?.Model),
        model_hash: stringValue(generation.model_hash ?? item.meta?.["Model hash"]),
        hires_steps: intValue(generation.hires_steps ?? item.meta?.["Hires steps"]),
        hires_upscale: numberValue(generation.hires_upscale ?? item.meta?.["Hires upscale"]),
        hires_upscaler: stringValue(generation.hires_upscaler ?? item.meta?.["Hires upscaler"]),
        hires_cfg: numberValue(generation.hires_cfg_scale ?? item.meta?.["Hires CFG Scale"]),
        token_merge: numberValue(generation.token_merging_ratio ?? item.meta?.["Token merging ratio"]),
        token_merge_hr: numberValue(generation.token_merging_ratio_hr ?? item.meta?.["Token merging ratio hr"]),
    });
    return {
        source: item.source || "",
        source_url: item.source_url || "",
        civitai_meta_id: item.meta?.civitai_meta_id || null,
        workflow_fields: workflowFields,
        carry_fields: carryFields,
        raw_generation: raw || {},
    };
}

function isDirectlyGeneratable(item) {
    return Boolean(reusablePrompt(item));
}

function titleOf(item) {
    return item.meta?.title || item.user_notes || firstTag(item) || item.visual_structure?.subject || `${item.source} #${item.source_id || item.id}`;
}

function descriptionOf(item) {
    return compact(reusablePrompt(item) || item.user_notes || referenceValue(item, "composition") || item.design_language?.layout || firstTag(item) || "没有描述");
}

function firstTag(item) {
    return (item.raw_tags || [])[0] || "";
}

function searchText(item) {
    return [
        titleOf(item),
        descriptionOf(item),
        reusablePrompt(item),
        styleBooster(item),
        ...referenceFields().map((field) => referenceValue(item, field.key)),
        item.creator,
        item.source,
        ...(item.raw_tags || []),
    ].join(" ").toLowerCase();
}

function promptSummaryEl(item) {
    const wrap = document.createElement("div");
    wrap.className = "prompt-summary";
    for (const field of promptFields()) {
        const row = document.createElement("span");
        row.innerHTML = `<b>${escapeHtml(field.label)}</b>${escapeHtml(field.value(item) || "未整理")}`;
        wrap.append(row);
    }
    return wrap;
}

function promptSummaryHtml(item) {
    return `
        <div class="prompt-summary">
            ${promptFields().map((field) => `
                <span><b>${escapeHtml(field.label)}</b>${escapeHtml(field.value(item) || "未整理")}</span>
            `).join("")}
        </div>
    `;
}

function promptFields() {
    return [
        { label: "可复用提示词", value: reusablePrompt },
        { label: "风格强化词", value: styleBooster },
    ];
}

function reusablePrompt(item) {
    return firstText(
        item.positive_prompt,
        item.prompts?.positive,
        item.prompt,
        item.meta?.prompt,
        item.meta?.Prompt,
        item.meta?.positivePrompt,
        item.meta?.["Positive prompt"],
    );
}

function styleBooster(item) {
    return referenceValue(item, "style_booster");
}

function referenceFields() {
    return [
        { key: "subject", label: "主体/角色" },
        { key: "composition", label: "构图" },
        { key: "color_palette", label: "色彩" },
        { key: "mood", label: "氛围" },
    ];
}

function referenceValue(item, key) {
    const visual = item.visual_structure || {};
    const value = visual[key];
    if (Array.isArray(value)) {
        return value.join("，");
    }
    return String(value || "").trim();
}

function referenceSummaryEl(item) {
    const wrap = document.createElement("div");
    wrap.className = "reference-summary";
    for (const field of referenceFields()) {
        const row = document.createElement("span");
        row.innerHTML = `<b>${escapeHtml(field.label)}</b>${escapeHtml(referenceValue(item, field.key) || "未整理")}`;
        wrap.append(row);
    }
    return wrap;
}

function referenceSummaryHtml(item) {
    return `
        <div class="reference-summary">
            ${referenceFields().map((field) => `
                <span><b>${escapeHtml(field.label)}</b>${escapeHtml(referenceValue(item, field.key) || "未整理")}</span>
            `).join("")}
        </div>
    `;
}

function parseNumberList(value) {
    return String(value || "")
        .split(/[,，\s]+/)
        .map((item) => Number(item.trim()))
        .filter((item) => Number.isFinite(item));
}

function compact(value) {
    return String(value || "").replace(/\s+/g, " ").slice(0, 140);
}

function firstText(...values) {
    for (const value of values) {
        const text = String(value ?? "").trim();
        if (text) {
            return text;
        }
    }
    return "";
}

function pruneEmpty(value) {
    return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== "" && item !== null && item !== undefined));
}

function stringValue(value) {
    return String(value ?? "").trim();
}

function numberValue(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function intValue(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.trunc(number) : null;
}

function textEl(tag, text) {
    const el = document.createElement(tag);
    el.textContent = text;
    return el;
}

function setSummary(text) {
    els.summary.textContent = text;
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

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
    return escapeHtml(value);
}
