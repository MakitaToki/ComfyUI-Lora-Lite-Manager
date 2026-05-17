import { collectionImageUrl, fetchArtworks } from "./collection_api.js";
import { fetchLoras, previewUrl } from "./api.js";
import { createExperimentRun, refreshExperimentRun, submitExperimentRunStep, previewExperiment } from "./experiment_api.js";

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
    loras: [
        { name: "Pvnk_styl2.safetensors", strengths: [0.4, 0.6, 0.8] },
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
    for (const input of [els.checkpointInput, els.stepsInput, els.widthInput, els.heightInput, els.seedsInput, els.promptModeInput]) {
        input.addEventListener("input", renderPreview);
    }
    els.promptModeInput.addEventListener("change", renderPreview);
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
    } catch (error) {
        showToast(`LoRA 列表读取失败：${error.message}`, true);
    }
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
            strengths: [0.4, 0.6, 0.8],
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
    const strengths = parseNumberList(els.loraStrengthInput.value);
    if (!name || !strengths.length) {
        showToast("请填写 LoRA 文件名和至少一个强度", true);
        return;
    }
    state.loras.push({ name, strengths });
    els.loraNameInput.value = "";
    els.loraStrengthInput.value = "";
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
    setRunProgress(null, "prepare", "准备实验任务", "正在创建 run，随后会逐个提交到 ComfyUI 队列。");
    try {
        const result = await createExperimentRun(buildRecipe(), { submit: false });
        let run = result.run;
        state.activeRunId = run.run_id;
        setRunProgress(run, "submit", "正在提交队列", "已创建 run，正在逐个提交 case。");

        while (hasPendingSubmissions(run)) {
            const step = await submitExperimentRunStep(run.run_id, { batchSize: 1 });
            run = step.run;
            const pending = hasPendingSubmissions(run);
            setRunProgress(run, pending ? "submit" : "queue", pending ? "正在提交队列" : "等待 / 执行中", latestRunMessage(run));
        }

        const refreshed = await refreshExperimentRun(run.run_id).catch(() => ({ run }));
        run = refreshed.run || run;
        setRunProgress(run, run.status === "completed" ? "done" : "queue", run.status === "completed" ? "已完成" : "已提交到 ComfyUI", latestRunMessage(run));
        showToast(`Experiment run created: ${run.run_id}`);
        window.setTimeout(() => {
            window.location.href = `/experiments-lite?run_id=${encodeURIComponent(run.run_id)}`;
        }, 1200);
    } catch (error) {
        setRunProgress(null, "error", "提交失败", error.message);
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
        size: preview.cases?.[0]?.generation ? `${preview.cases[0].generation.width} × ${preview.cases[0].generation.height}` : `${els.widthInput.value} × ${els.heightInput.value}`,
        warning: summary.warning,
    });
}

function renderSummaryCards(summary) {
    els.experimentPreviewSummary.hidden = false;
    els.experimentPreviewSummary.innerHTML = `
        <div><strong>${summary.total || 0}</strong><span>images</span></div>
        <div><strong>${summary.promptVariants || 0}</strong><span>prompt variants</span></div>
        <div><strong>${summary.loraCombos || 0}</strong><span>LoRA combos</span></div>
        <div><strong>${summary.strengths || 0}</strong><span>strengths</span></div>
        <div><strong>${summary.seeds || 0}</strong><span>seeds</span></div>
        <div><strong>${escapeHtml(summary.checkpoint || "-")}</strong><span>checkpoint</span></div>
        <div><strong>${escapeHtml(summary.size || "-")}</strong><span>size</span></div>
        ${summary.warning ? `<p>${escapeHtml(summary.warning)}</p>` : ""}
    `;
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

function setRunProgress(run, stage, title, message) {
    els.runProgressPanel.hidden = false;
    els.runProgressTitle.textContent = title;
    els.runProgressMessage.textContent = message || "";
    els.runProgressPanel.dataset.stage = stage;
    const stats = runStats(run);
    const percent = stats.total ? Math.round(((stats.queued + stats.completed + stats.error) / stats.total) * 100) : 0;
    els.runProgressBar.style.width = `${percent}%`;
    els.runProgressStats.innerHTML = `
        <span>总数 ${stats.total}</span>
        <span>已提交 ${stats.queued + stats.completed}</span>
        <span>完成 ${stats.completed}</span>
        <span>失败 ${stats.error}</span>
    `;
    els.openRunBtn.hidden = !run?.run_id;
    if (run?.run_id) {
        els.openRunBtn.href = `/experiments-lite?run_id=${encodeURIComponent(run.run_id)}`;
    }
}

function runStats(run) {
    const submissions = run?.submissions || [];
    const total = run?.preview?.summary?.total || submissions.length || 0;
    return {
        total,
        pending: submissions.filter((item) => item.status === "pending").length,
        queued: submissions.filter((item) => ["queued", "submitted"].includes(item.status)).length,
        completed: submissions.filter((item) => item.status === "completed").length,
        error: submissions.filter((item) => item.status === "error").length,
    };
}

function latestRunMessage(run) {
    const stats = runStats(run);
    if (stats.error) {
        const failed = (run.submissions || []).find((item) => item.status === "error");
        return `有 ${stats.error} 个 case 提交失败。${failed?.error || ""}`;
    }
    if (stats.pending) {
        return `还剩 ${stats.pending} 个 case 等待提交。`;
    }
    if (run?.status === "completed") {
        return "ComfyUI 已生成完成。";
    }
    return "所有 case 已提交到 ComfyUI，正在等待或执行。";
}

function buildRecipe() {
    return {
        recipe_id: "lora_strength_test",
        name: "LoRA 强度测试",
        main_artwork: state.main ? artworkRef(state.main) : null,
        visual_references: state.refs.map((item) => ({ ...artworkRef(item), usage: item.usage })),
        lora_matrix: state.loras.map((item) => ({
            name: item.name,
            strengths: item.strengths,
            notes: item.notes || "",
            trigger_words: item.trigger_words || [],
            base_model: item.base_model || "",
            source_url: item.source_url || "",
            download_url: item.download_url || "",
        })),
        seeds: parseNumberList(els.seedsInput.value).map((value) => Math.trunc(value)),
        prompt_mode: els.promptModeInput.value,
        generation: {
            checkpoint: els.checkpointInput.value.trim(),
            steps: Number(els.stepsInput.value) || 22,
            width: Number(els.widthInput.value) || 832,
            height: Number(els.heightInput.value) || 1216,
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
    return [...new Set(state.loras.flatMap((item) => item.strengths).map((value) => Number(value)).filter((value) => Number.isFinite(value)))];
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

function artworkRef(item) {
    return {
        id: item.id,
        title: titleOf(item),
        source: item.source,
        source_url: item.source_url,
        asset_type: item.asset_type,
        prompt_state: isDirectlyGeneratable(item) ? "可直接生成" : "需要整理提示词",
    };
}

function artworkSlotHtml(item, badge, removable) {
    return `
        <img src="${escapeAttr(collectionImageUrl(item.preview_path || item.image_url))}" alt="">
        <div class="slot-text">
            <span>${escapeHtml(badge)} · ${isDirectlyGeneratable(item) ? "可直接生成" : "需要整理"}</span>
            <strong>${escapeHtml(titleOf(item))}</strong>
            <p>${escapeHtml(descriptionOf(item))}</p>
            ${promptSummaryHtml(item)}
            ${referenceSummaryHtml(item)}
        </div>
        ${removable ? '<button class="icon-button" type="button" aria-label="移除">x</button>' : ""}
    `;
}

function isDirectlyGeneratable(item) {
    return Boolean(String(item.positive_prompt || "").trim());
}

function titleOf(item) {
    return item.meta?.title || item.user_notes || firstTag(item) || item.visual_structure?.subject || `${item.source} #${item.source_id || item.id}`;
}

function descriptionOf(item) {
    return compact(item.positive_prompt || item.user_notes || referenceValue(item, "composition") || item.design_language?.layout || firstTag(item) || "没有描述");
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
    return String(item.positive_prompt || "").trim();
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
