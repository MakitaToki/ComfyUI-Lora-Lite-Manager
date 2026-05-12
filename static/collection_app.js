import { addManualReference, collectionImageUrl, exportSeeds, fetchArtworks, fetchArtwork, importCivitaiUrl } from "./collection_api.js";

const state = {
    items: [],
    query: "",
    sort: "newest",
    selectedId: "",
};

const els = {
    importForm: document.querySelector("#importForm"),
    importUrl: document.querySelector("#importUrl"),
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
    if (!url) {
        showToast("先粘贴一条 Civitai 图片链接");
        return;
    }

    setBusy(true, "正在导入这张 Civitai 图片...");
    try {
        const result = await importCivitaiUrl({ url });
        els.importUrl.value = "";
        showToast(result.count ? "图片已导入" : "没有找到这张图片");
        await loadItems();
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
    els.detailsTitle.textContent = firstTag(item) || `Civitai #${item.source_id}`;
    els.detailsBody.replaceChildren();

    const img = document.createElement("img");
    img.className = "detail-image";
    img.src = collectionImageUrl(item.preview_path || item.image_url);
    img.alt = firstTag(item) || item.source_id;
    els.detailsBody.append(img);

    els.detailsBody.append(section("素材类型", assetTypeLabel(item.asset_type)));
    els.detailsBody.append(section("正向提示词", item.positive_prompt || "无"));
    els.detailsBody.append(section("负向提示词", item.negative_prompt || "无"));
    els.detailsBody.append(jsonSection("视觉结构", item.visual_structure || {}));
    els.detailsBody.append(jsonSection("设计语言", item.design_language || {}));
    els.detailsBody.append(jsonSection("迁移规则", item.transfer || {}));
    els.detailsBody.append(section("备注", item.user_notes || "无"));
    els.detailsBody.append(tagSection(item.raw_tags || []));
    els.detailsBody.append(modelSection(item.model_refs || []));

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
        const row = textEl("div", [model.name, model.type, model.weight ? `w=${model.weight}` : ""].filter(Boolean).join(" · "));
        list.append(row);
    }
    if (!models.length) {
        list.append(textEl("div", "无"));
    }
    block.append(list);
    return block;
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
    return firstTag(item) || item.visual_structure?.subject || item.retrieval?.embedding_text || `${item.source} #${item.source_id}`;
}

function cardDescription(item) {
    return item.positive_prompt || item.user_notes || item.visual_structure?.composition || item.design_language?.layout || "无描述";
}

function assetTypeLabel(value) {
    return {
        ai_generation_reference: "AI / 插画生成参考",
        photo_reference: "摄影参考",
        graphic_design_reference: "平面设计参考",
    }[value] || "参考素材";
}

function splitTags(value) {
    return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
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
