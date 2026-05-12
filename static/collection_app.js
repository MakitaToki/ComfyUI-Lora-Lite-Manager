import { collectionImageUrl, exportSeeds, fetchArtworks, fetchArtwork, importCivitaiUrl } from "./collection_api.js";

const state = {
    items: [],
    query: "",
    sort: "newest",
    selectedId: "",
};

const els = {
    importForm: document.querySelector("#importForm"),
    importUrl: document.querySelector("#importUrl"),
    importLimit: document.querySelector("#importLimit"),
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
    els.searchInput.addEventListener("input", debounce(handleSearch, 180));
    els.sortSelect.addEventListener("change", handleSort);
    els.refreshBtn.addEventListener("click", () => loadItems());
    els.exportBtn.addEventListener("click", handleExport);
    els.closeExportBtn.addEventListener("click", () => {
        els.exportDialog.hidden = true;
    });
    loadItems();
}

async function handleImport(event) {
    event.preventDefault();
    const url = els.importUrl.value.trim();
    const limit = Number(els.importLimit.value || 20);
    if (!url) {
        showToast("先粘贴一个 Civitai 链接");
        return;
    }

    setBusy(true, "正在拉取 Civitai 元数据和缩略图...");
    try {
        const result = await importCivitaiUrl({ url, limit });
        els.importUrl.value = "";
        showToast(`已导入 ${result.count} 张作品`);
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
        body.append(textEl("strong", firstTag(item) || `Civitai #${item.source_id}`));
        body.append(textEl("span", compactPrompt(item.positive_prompt)));
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

    els.detailsBody.append(section("正向提示词", item.positive_prompt || "无"));
    els.detailsBody.append(section("负向提示词", item.negative_prompt || "无"));
    els.detailsBody.append(tagSection(item.raw_tags || []));
    els.detailsBody.append(modelSection(item.model_refs || []));

    const link = document.createElement("a");
    link.className = "button secondary wide";
    link.href = item.source_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = loading ? "正在补全详情..." : "打开 Civitai 原图";
    els.detailsBody.append(link);
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

function section(title, content) {
    const block = document.createElement("section");
    block.className = "detail-section";
    block.append(textEl("h3", title));
    block.append(textEl("p", content));
    return block;
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
    row.append(textEl("span", `♡ ${stats.heartCount ?? 0}`));
    row.append(textEl("span", `赞 ${stats.likeCount ?? 0}`));
    return row;
}

function compactPrompt(value) {
    return (value || "无提示词").replace(/\s+/g, " ").slice(0, 120);
}

function firstTag(item) {
    return (item.raw_tags || [])[0] || "";
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

