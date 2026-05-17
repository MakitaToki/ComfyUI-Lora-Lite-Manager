import { addManualReference, collectionImageUrl, deleteArtwork, exportSeeds, fetchArtworks, fetchArtwork, importCivitaiUrl, updateArtwork } from "./collection_api.js";

const state = {
    items: [],
    query: "",
    sort: "newest",
    selectedId: "",
};

const els = {
    importForm: document.querySelector("#importForm"),
    importUrl: document.querySelector("#importUrl"),
    importTitle: document.querySelector("#importTitle"),
    manualForm: document.querySelector("#manualForm"),
    manualAssetType: document.querySelector("#manualAssetType"),
    manualPlatform: document.querySelector("#manualPlatform"),
    manualSourceUrl: document.querySelector("#manualSourceUrl"),
    manualImageUrl: document.querySelector("#manualImageUrl"),
    manualLocalPath: document.querySelector("#manualLocalPath"),
    manualSubject: document.querySelector("#manualSubject"),
    manualComposition: document.querySelector("#manualComposition"),
    manualColorLighting: document.querySelector("#manualColorLighting"),
    manualDesignLanguage: document.querySelector("#manualDesignLanguage"),
    manualTags: document.querySelector("#manualTags"),
    manualNotes: document.querySelector("#manualNotes"),
    searchInput: document.querySelector("#searchInput"),
    sortSelect: document.querySelector("#sortSelect"),
    refreshBtn: document.querySelector("#refreshBtn"),
    exportBtn: document.querySelector("#exportBtn"),
    grid: document.querySelector("#grid"),
    emptyState: document.querySelector("#emptyState"),
    summary: document.querySelector("#summary"),
    detailsTitle: document.querySelector("#detailsTitle"),
    detailsBody: document.querySelector("#detailsBody"),
    exportDialog: document.querySelector("#exportDialog"),
    exportText: document.querySelector("#exportText"),
    closeExportBtn: document.querySelector("#closeExportBtn"),
    toast: document.querySelector("#toast"),
};

init();

function init() {
    els.importForm.addEventListener("submit", handleImport);
    els.manualForm.addEventListener("submit", handleManualAdd);
    els.searchInput.addEventListener("input", debounce(handleSearch, 180));
    els.sortSelect.addEventListener("change", handleSort);
    els.refreshBtn.addEventListener("click", () => loadItems());
    els.exportBtn.addEventListener("click", handleExport);
    els.closeExportBtn.addEventListener("click", closeExportDialog);
    els.exportDialog.addEventListener("click", (event) => {
        if (event.target === els.exportDialog) {
            closeExportDialog();
        }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !els.exportDialog.hidden) {
            closeExportDialog();
        }
    });
    loadItems();
}

async function handleImport(event) {
    event.preventDefault();
    const url = els.importUrl.value.trim();
    const title = els.importTitle.value.trim();
    if (!url) {
        showToast("先粘贴一条 Civitai 图片链接");
        return;
    }

    setBusy(true, "正在导入这张 Civitai 图片...");
    try {
        const result = await importCivitaiUrl({ url, title });
        els.importUrl.value = "";
        els.importTitle.value = "";
        showToast(result.count ? "图片已导入" : "没有找到这张图片");
        await loadItems();
        if (result.items?.[0]?.id) {
            await selectItem(result.items[0].id);
        }
    } catch (error) {
        showToast(error.message, true);
    } finally {
        setBusy(false);
    }
}

async function handleManualAdd(event) {
    event.preventDefault();
    const imageUrl = els.manualImageUrl.value.trim();
    const localPath = els.manualLocalPath.value.trim();
    if (!imageUrl && !localPath) {
        showToast("图片 URL 和本地图片路径至少填一个");
        return;
    }

    const assetType = els.manualAssetType.value;
    const subject = els.manualSubject.value.trim();
    const composition = els.manualComposition.value.trim();
    const colorLighting = els.manualColorLighting.value.trim();
    const designLanguage = els.manualDesignLanguage.value.trim();
    const tags = splitTags(els.manualTags.value);

    setBusy(true, "正在保存视觉参考...");
    try {
        await addManualReference({
            asset_type: assetType,
            source: {
                platform: els.manualPlatform.value.trim() || (localPath ? "local" : "web"),
                source_url: els.manualSourceUrl.value.trim(),
                image_url: imageUrl,
                local_image_path: localPath,
            },
            tags,
            visual_structure: {
                subject,
                composition,
                lighting: colorLighting,
                color_palette: splitTags(colorLighting),
                mood: "",
            },
            design_language: {
                color: colorLighting,
                typography: assetType === "graphic_design_reference" ? designLanguage : "",
                layout: composition,
                imagery: subject,
                post_process: designLanguage,
            },
            retrieval: {
                keywords_zh: tags,
                keywords_en: [],
                embedding_text: [subject, composition, colorLighting, designLanguage, els.manualNotes.value.trim()].filter(Boolean).join("，"),
            },
            positive_prompt: "",
            negative_prompt: assetType === "graphic_design_reference" ? "text, logo, watermark, distorted typography" : "",
            user_notes: els.manualNotes.value.trim(),
        });
        els.manualForm.reset();
        showToast("视觉参考已保存");
        await loadItems();
    } catch (error) {
        showToast(error.message, true);
    } finally {
        setBusy(false);
    }
}

function handleSearch() {
    state.query = els.searchInput.value.trim();
    loadItems();
}

function handleSort() {
    state.sort = els.sortSelect.value;
    loadItems();
}

async function loadItems() {
    setBusy(true, "正在读取作品集...");
    try {
        const result = await fetchArtworks({ query: state.query, sort: state.sort });
        state.items = result.items;
        renderGrid();
        els.summary.textContent = `${result.total} 张作品`;
    } catch (error) {
        showToast(error.message, true);
    } finally {
        setBusy(false);
    }
}

function renderGrid() {
    els.grid.replaceChildren();
    els.emptyState.hidden = state.items.length > 0;

    for (const item of state.items) {
        const card = document.createElement("button");
        card.className = "art-card";
        card.type = "button";
        card.dataset.id = item.id;
        card.addEventListener("click", () => selectItem(item.id));

        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = collectionImageUrl(item.preview_path || item.image_url);
        img.alt = firstTag(item) || item.source_id;
        card.append(img);

        const body = document.createElement("div");
        body.className = "art-card-body";
        body.append(textEl("strong", cardTitle(item)));
        body.append(textEl("span", assetTypeLabel(item.asset_type)));
        body.append(textEl("span", compactPrompt(cardDescription(item))));
        body.append(renderStats(item));
        card.append(body);

        els.grid.append(card);
    }
}

async function selectItem(id) {
    state.selectedId = id;
    const local = state.items.find((item) => item.id === id);
    renderDetails(local, true);
    try {
        const result = await fetchArtwork(id);
        renderDetails(result.item, false);
    } catch (error) {
        showToast(error.message, true);
    }
}

function renderDetails(item, loading) {
    if (!item) {
        return;
    }
    els.detailsTitle.textContent = cardTitle(item);
    els.detailsBody.replaceChildren();

    const img = document.createElement("img");
    img.className = "detail-image";
    img.src = collectionImageUrl(item.preview_path || item.image_url);
    img.alt = firstTag(item) || item.source_id;
    els.detailsBody.append(img);

    const actions = document.createElement("div");
    actions.className = "detail-actions";
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "button danger wide";
    deleteBtn.type = "button";
    deleteBtn.textContent = "删除这张作品";
    deleteBtn.addEventListener("click", () => handleDelete(item));
    actions.append(deleteBtn);
    els.detailsBody.append(actions);

    els.detailsBody.append(assetTypeEditor(item));
    els.detailsBody.append(referenceInfoEditor(item));
    els.detailsBody.append(section("备注", item.user_notes || "无"));
    els.detailsBody.append(generationSection(item));
    els.detailsBody.append(modelSection(item.model_refs || []));
    els.detailsBody.append(section("正向提示词", item.positive_prompt || "无"));
    els.detailsBody.append(section("负向提示词", item.negative_prompt || "无"));
    els.detailsBody.append(jsonSection("设计语言", item.design_language || {}));
    els.detailsBody.append(jsonSection("迁移规则", item.transfer || {}));
    els.detailsBody.append(tagSection(item.raw_tags || []));
    els.detailsBody.append(metaDebugSection(item));

    const link = document.createElement("a");
    link.className = "button secondary wide";
    link.href = item.source_url || item.image_url || "#";
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = loading ? "正在补全详情..." : "打开来源";
    if (item.source_url || item.image_url) {
        els.detailsBody.append(link);
    }
}

async function handleDelete(item) {
    if (!item?.id) {
        return;
    }
    if (!window.confirm(`删除 ${cardTitle(item)}？`)) {
        return;
    }
    setBusy(true, "正在删除作品...");
    try {
        await deleteArtwork(item.id);
        state.selectedId = "";
        els.detailsTitle.textContent = "选择作品";
        els.detailsBody.className = "details-empty";
        els.detailsBody.textContent = "从左侧作品卡片开始。";
        showToast("作品已删除");
        await loadItems();
    } catch (error) {
        showToast(error.message, true);
    } finally {
        setBusy(false);
    }
}

async function handleExport() {
    setBusy(true, "正在生成 Creative Seeds...");
    try {
        const result = await exportSeeds({ query: state.query, sort: "popular", limit: 100 });
        els.exportText.value = JSON.stringify(result, null, 2);
        els.exportDialog.hidden = false;
        showToast(`已导出 ${result.seeds.length} 条 Creative Seeds`);
    } catch (error) {
        showToast(error.message, true);
    } finally {
        setBusy(false);
    }
}

function closeExportDialog() {
    els.exportDialog.hidden = true;
}

function section(title, content) {
    const block = document.createElement("section");
    block.className = "detail-section";
    block.append(textEl("h3", title));
    block.append(textEl("p", content));
    return block;
}

function assetTypeEditor(item) {
    const block = document.createElement("section");
    block.className = "detail-section";
    block.append(textEl("h3", "素材类型"));

    const select = document.createElement("select");
    select.className = "detail-select";
    for (const [value, label] of Object.entries(assetTypeOptions())) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        option.selected = value === item.asset_type;
        select.append(option);
    }
    select.addEventListener("change", () => handleAssetTypeChange(item, select.value));
    block.append(select);
    return block;
}

function referenceInfoEditor(item) {
    const block = document.createElement("section");
    block.className = "detail-section reference-info-section";
    block.append(textEl("h3", "参考信息"));

    const form = document.createElement("form");
    form.className = "reference-info-form";
    for (const field of referenceFields()) {
        const label = document.createElement("label");
        label.append(textEl("span", field.label));
        const input = document.createElement("textarea");
        input.name = field.key;
        input.rows = 2;
        input.value = referenceValue(item, field.key);
        input.placeholder = field.placeholder;
        label.append(input);
        form.append(label);
    }

    const saveBtn = document.createElement("button");
    saveBtn.className = "button primary wide";
    saveBtn.type = "submit";
    saveBtn.textContent = "保存参考信息";
    form.append(saveBtn);
    form.addEventListener("submit", (event) => handleReferenceInfoSave(event, item));

    block.append(form);
    return block;
}

async function handleReferenceInfoSave(event, item) {
    event.preventDefault();
    if (!item?.id) {
        return;
    }

    const form = event.currentTarget;
    const visualStructure = { ...(item.visual_structure || {}) };
    for (const field of referenceFields()) {
        const value = form.elements[field.key]?.value || "";
        visualStructure[field.key] = field.key === "color_palette"
            ? splitTags(value)
            : value.trim();
    }

    setBusy(true, "正在保存参考信息...");
    try {
        const result = await updateArtwork(item.id, { visual_structure: visualStructure });
        showToast("参考信息已保存");
        await loadItems();
        renderDetails(result.item, false);
    } catch (error) {
        showToast(error.message, true);
    } finally {
        setBusy(false);
    }
}

async function handleAssetTypeChange(item, assetType) {
    if (!item?.id || assetType === item.asset_type) {
        return;
    }
    setBusy(true, "正在更新素材类型...");
    try {
        const result = await updateArtwork(item.id, { asset_type: assetType });
        showToast("素材类型已更新");
        await loadItems();
        renderDetails(result.item, false);
    } catch (error) {
        showToast(error.message, true);
        renderDetails(item, false);
    } finally {
        setBusy(false);
    }
}

function referenceFields() {
    return [
        { key: "subject", label: "主体/角色", placeholder: "例如：半身少女、产品主体、室内空间" },
        { key: "composition", label: "构图", placeholder: "例如：中心聚焦、半身像占中下区域、背景横向平衡" },
        { key: "color_palette", label: "色彩", placeholder: "例如：荧光黄、亮蓝、玫红、黑灰" },
        { key: "mood", label: "氛围", placeholder: "例如：街头、甜酷、涂鸦、霓虹" },
    ];
}

function referenceValue(item, key) {
    const visual = item.visual_structure || {};
    const value = visual[key];
    if (Array.isArray(value)) {
        return value.join("，");
    }
    return String(value || "");
}

function jsonSection(title, value) {
    const content = Object.entries(value)
        .filter(([, item]) => item !== "" && item !== null && item !== undefined && (!Array.isArray(item) || item.length))
        .map(([key, item]) => `${key}: ${Array.isArray(item) ? item.join(", ") : item}`)
        .join("\n");
    return section(title, content || "无");
}

function tagSection(tags) {
    const block = document.createElement("section");
    block.className = "detail-section";
    block.append(textEl("h3", "Tags"));
    const wrap = document.createElement("div");
    wrap.className = "tags";
    for (const tag of tags.slice(0, 80)) {
        wrap.append(textEl("span", tag));
    }
    block.append(wrap);
    return block;
}

function modelSection(models) {
    const block = document.createElement("section");
    block.className = "detail-section";
    block.append(textEl("h3", "模型引用"));
    const list = document.createElement("div");
    list.className = "model-list";
    for (const model of models.slice(0, 20)) {
        const row = textEl("div", [
            model.name,
            model.version ? `v${model.version}` : "",
            model.type,
            model.weight ? `weight ${model.weight}` : "",
        ].filter(Boolean).join(" · "));
        list.append(row);
    }
    if (!models.length) {
        list.append(textEl("div", "无"));
    }
    block.append(list);
    return block;
}

function generationSection(item) {
    const generation = item.aigc_seed || item.meta?.generation || {};
    const rows = [
        ["CFG", generation.cfg_scale],
        ["Steps", generation.steps],
        ["Sampler", generation.sampler],
        ["Seed", generation.seed],
        ["Clip skip", generation.clip_skip],
        ["Size", generation.size || sizeFromGeneration(generation)],
        ["Model", generation.model],
        ["Model hash", generation.model_hash],
        ["Schedule", generation.schedule_type || generation.scheduler],
        ["Hires steps", generation.hires_steps],
        ["Hires upscale", generation.hires_upscale],
        ["Hires upscaler", generation.hires_upscaler],
        ["Hires CFG", generation.hires_cfg_scale],
        ["Denoising", generation.denoising_strength],
        ["Token merge", generation.token_merging_ratio],
        ["Token merge HR", generation.token_merging_ratio_hr],
    ].filter(([, value]) => value !== "" && value !== null && value !== undefined);

    const block = document.createElement("section");
    block.className = "detail-section";
    block.append(textEl("h3", "Generation data"));
    if (!rows.length) {
        block.append(textEl("p", "无"));
        return block;
    }

    const chips = document.createElement("div");
    chips.className = "meta-chips";
    for (const [label, value] of rows) {
        const chip = textEl("span", `${label}: ${value}`);
        chips.append(chip);
    }
    block.append(chips);
    return block;
}

function metaDebugSection(item) {
    const meta = item.meta || {};
    const keys = Object.keys(meta).filter((key) => key !== "generation");
    if (!keys.length) {
        return section("Civitai meta keys", "无");
    }
    return section("Civitai meta keys", keys.join(", "));
}

function renderStats(item) {
    const stats = item.stats || {};
    const row = document.createElement("div");
    row.className = "stats";
    if (item.source === "civitai") {
        row.append(textEl("span", `♡ ${stats.heartCount ?? 0}`));
        row.append(textEl("span", `赞 ${stats.likeCount ?? 0}`));
    } else {
        row.append(textEl("span", item.source || "manual"));
    }
    return row;
}

function compactPrompt(value) {
    return (value || "无提示词").replace(/\s+/g, " ").slice(0, 120);
}

function firstTag(item) {
    return (item.raw_tags || [])[0] || "";
}

function cardTitle(item) {
    return item.meta?.title || item.user_notes || firstTag(item) || item.visual_structure?.subject || item.retrieval?.embedding_text || `${item.source} #${item.source_id}`;
}

function cardDescription(item) {
    return item.positive_prompt || item.user_notes || item.visual_structure?.composition || item.design_language?.layout || "无描述";
}

function assetTypeLabel(value) {
    return assetTypeOptions()[value] || "参考素材";
}

function assetTypeOptions() {
    return {
        ai_generation_reference: "AI / 插画生成参考",
        photo_reference: "摄影参考",
        graphic_design_reference: "平面设计参考",
    };
}

function splitTags(value) {
    return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
}

function sizeFromGeneration(generation) {
    if (generation.width && generation.height) {
        return `${generation.width}x${generation.height}`;
    }
    return "";
}

function textEl(tag, text) {
    const el = document.createElement(tag);
    el.textContent = text;
    return el;
}

function setBusy(isBusy, label = "") {
    document.body.classList.toggle("is-busy", isBusy);
    if (label) {
        els.summary.textContent = label;
    }
}

function showToast(message, isError = false) {
    els.toast.textContent = message;
    els.toast.classList.toggle("error", isError);
    els.toast.hidden = false;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        els.toast.hidden = true;
    }, 4200);
}

function debounce(fn, wait) {
    let timer = 0;
    return (...args) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => fn(...args), wait);
    };
}
