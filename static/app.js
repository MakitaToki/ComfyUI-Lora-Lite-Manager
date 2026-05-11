import {
    calculateHash,
    downloadLora,
    fetchCivitaiByHash,
    fetchLoras,
    fetchRoots,
    previewUrl,
    saveMetadata,
} from "./api.js";

const state = {
    items: [],
    roots: [],
    selected: null,
    search: "",
    root: "",
};

const els = {
    summary: document.getElementById("summary"),
    refreshBtn: document.getElementById("refreshBtn"),
    downloadPanelBtn: document.getElementById("downloadPanelBtn"),
    searchInput: document.getElementById("searchInput"),
    rootFilter: document.getElementById("rootFilter"),
    grid: document.getElementById("grid"),
    emptyState: document.getElementById("emptyState"),
    detailsTitle: document.getElementById("detailsTitle"),
    detailsPath: document.getElementById("detailsPath"),
    detailsBody: document.getElementById("detailsBody"),
    downloadDrawer: document.getElementById("downloadDrawer"),
    closeDownloadBtn: document.getElementById("closeDownloadBtn"),
    downloadForm: document.getElementById("downloadForm"),
    downloadInput: document.getElementById("downloadInput"),
    downloadRoot: document.getElementById("downloadRoot"),
    downloadSubdir: document.getElementById("downloadSubdir"),
    toast: document.getElementById("toast"),
};

function formatBytes(value) {
    if (!Number.isFinite(value) || value <= 0) {
        return "";
    }
    const units = ["B", "KB", "MB", "GB"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit += 1;
    }
    return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function toast(message, kind = "info") {
    els.toast.textContent = message;
    els.toast.dataset.kind = kind;
    els.toast.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => {
        els.toast.hidden = true;
    }, 3200);
}

function normalizeWords(value) {
    if (Array.isArray(value)) {
        return value.map(String).map((item) => item.trim()).filter(Boolean);
    }
    return String(value || "")
        .split(/[,，\n]/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function itemText(item) {
    const metadata = item.metadata || {};
    return [
        item.name,
        item.file_name,
        item.relative_path,
        item.base_model,
        item.notes,
        ...(item.tags || []),
        ...(item.trigger_words || metadata.trigger_words || metadata.trained_words || []),
    ].join(" ").toLowerCase();
}

function filteredItems() {
    const query = state.search.trim().toLowerCase();
    return state.items.filter((item) => {
        if (state.root && item.root !== state.root) {
            return false;
        }
        if (!query) {
            return true;
        }
        return itemText(item).includes(query);
    });
}

function renderRoots() {
    const options = ['<option value="">全部</option>'];
    for (const root of state.roots) {
        options.push(`<option value="${escapeAttr(root)}">${escapeHtml(root)}</option>`);
    }
    els.rootFilter.innerHTML = options.join("");
    els.downloadRoot.innerHTML = state.roots
        .map((root) => `<option value="${escapeAttr(root)}">${escapeHtml(root)}</option>`)
        .join("");
}

function renderGrid() {
    const items = filteredItems();
    els.summary.textContent = `共 ${state.items.length} 个 LoRA，当前显示 ${items.length} 个`;
    els.emptyState.hidden = items.length > 0;

    els.grid.innerHTML = items.map((item) => cardHtml(item)).join("");
    els.grid.querySelectorAll(".card").forEach((card) => {
        card.addEventListener("click", () => selectItem(card.dataset.path));
    });
}

function cardHtml(item) {
    const image = previewUrl(item.preview_path);
    const selected = state.selected?.file_path === item.file_path ? " selected" : "";
    const words = item.trigger_words || [];
    const civitai = item.civitai || {};
    const versionId = civitai.modelVersionId || civitai.version?.id || "";

    return `
        <article class="card${selected}" data-path="${escapeAttr(item.file_path)}">
            <div class="thumb ${image ? "" : "empty-thumb"}">
                ${image ? `<img src="${escapeAttr(image)}" alt="">` : "<span>LoRA</span>"}
            </div>
            <div class="card-body">
                <h3>${escapeHtml(item.name)}</h3>
                <p>${escapeHtml(item.relative_path)}</p>
                <div class="meta-row">
                    ${item.base_model ? `<span>${escapeHtml(item.base_model)}</span>` : ""}
                    ${formatBytes(item.size) ? `<span>${formatBytes(item.size)}</span>` : ""}
                    ${versionId ? `<span>Civitai #${escapeHtml(versionId)}</span>` : ""}
                </div>
                ${words.length ? `<div class="chips">${words.slice(0, 5).map((word) => `<span>${escapeHtml(word)}</span>`).join("")}</div>` : ""}
            </div>
        </article>
    `;
}

function selectItem(filePath) {
    state.selected = state.items.find((item) => item.file_path === filePath) || null;
    renderGrid();
    renderDetails();
}

function renderDetails() {
    const item = state.selected;
    if (!item) {
        els.detailsTitle.textContent = "选择一个 LoRA";
        els.detailsPath.textContent = "查看和编辑元数据";
        els.detailsBody.className = "details-empty";
        els.detailsBody.textContent = "从左侧选择一张卡片，或者先点击刷新扫描本地模型。";
        return;
    }

    const metadata = item.metadata || {};
    const triggerWords = item.trigger_words || metadata.trigger_words || metadata.trained_words || [];
    const civitai = item.civitai || {};
    const versionId = civitai.modelVersionId || civitai.version?.id || "";
    const modelId = civitai.modelId || civitai.model?.id || "";

    els.detailsTitle.textContent = item.name;
    els.detailsPath.textContent = item.file_path;
    els.detailsBody.className = "";
    els.detailsBody.innerHTML = `
        <div class="details-preview">
            ${previewUrl(item.preview_path) ? `<img src="${escapeAttr(previewUrl(item.preview_path))}" alt="">` : "<div>无预览图</div>"}
        </div>
        <div class="facts">
            <div><span>文件名</span><strong>${escapeHtml(item.file_name)}</strong></div>
            <div><span>大小</span><strong>${escapeHtml(formatBytes(item.size))}</strong></div>
            <div><span>基础模型</span><strong>${escapeHtml(item.base_model || "-")}</strong></div>
            <div><span>SHA256</span><strong>${escapeHtml(item.sha256 || "未计算")}</strong></div>
            <div><span>Civitai</span><strong>${modelId || versionId ? `Model ${escapeHtml(modelId || "-")} / Version ${escapeHtml(versionId || "-")}` : "未关联"}</strong></div>
        </div>
        <form id="metadataForm" class="form">
            <label>
                <span>显示名称</span>
                <input id="modelNameInput" value="${escapeAttr(metadata.model_name || item.name)}">
            </label>
            <label>
                <span>触发词，用逗号或换行分隔</span>
                <textarea id="triggerWordsInput" rows="3">${escapeHtml(triggerWords.join(", "))}</textarea>
            </label>
            <label>
                <span>备注</span>
                <textarea id="notesInput" rows="5">${escapeHtml(metadata.notes || item.notes || "")}</textarea>
            </label>
            <div class="action-row">
                <button class="button primary" type="submit">保存备注/触发词</button>
                <button id="hashBtn" class="button secondary" type="button">计算哈希</button>
                <button id="civitaiBtn" class="button secondary" type="button">匹配 Civitai</button>
            </div>
        </form>
    `;

    document.getElementById("metadataForm").addEventListener("submit", saveSelectedMetadata);
    document.getElementById("hashBtn").addEventListener("click", hashSelected);
    document.getElementById("civitaiBtn").addEventListener("click", matchSelectedCivitai);
}

async function saveSelectedMetadata(event) {
    event.preventDefault();
    if (!state.selected) {
        return;
    }

    const metadata = {
        ...(state.selected.metadata || {}),
        model_name: document.getElementById("modelNameInput").value.trim() || state.selected.name,
        trigger_words: normalizeWords(document.getElementById("triggerWordsInput").value),
        trained_words: normalizeWords(document.getElementById("triggerWordsInput").value),
        notes: document.getElementById("notesInput").value.trim(),
    };

    await saveAndRefresh(metadata, "已保存元数据");
}

async function hashSelected() {
    if (!state.selected) {
        return;
    }
    setBusy(true, "正在计算哈希...");
    try {
        const result = await calculateHash(state.selected.file_path);
        const metadata = { ...(state.selected.metadata || {}), sha256: result.sha256 };
        await saveAndRefresh(metadata, "哈希已计算");
    } catch (error) {
        toast(error.message, "error");
    } finally {
        setBusy(false);
    }
}

async function matchSelectedCivitai() {
    if (!state.selected) {
        return;
    }
    setBusy(true, "正在匹配 Civitai...");
    try {
        let sha256 = state.selected.sha256;
        if (!sha256) {
            const hashResult = await calculateHash(state.selected.file_path);
            sha256 = hashResult.sha256;
        }
        const result = await fetchCivitaiByHash(sha256);
        const version = result.result || {};
        const metadata = metadataFromCivitai(state.selected, version, sha256);
        await saveAndRefresh(metadata, "已关联 Civitai 元数据");
    } catch (error) {
        toast(error.message, "error");
    } finally {
        setBusy(false);
    }
}

function metadataFromCivitai(item, version, sha256) {
    const model = version.model || {};
    const images = Array.isArray(version.images) ? version.images : [];
    const image = images.find((entry) => entry?.url) || {};
    const trainedWords = Array.isArray(version.trainedWords) ? version.trainedWords : [];

    return {
        ...(item.metadata || {}),
        model_name: model.name || version.name || item.name,
        file_name: item.file_name,
        file_path: item.file_path,
        base_model: version.baseModel || item.base_model || "",
        sha256,
        trigger_words: trainedWords,
        trained_words: trainedWords,
        preview_url: image.url || item.metadata?.preview_url || "",
        civitai: {
            modelId: model.id || null,
            modelVersionId: version.id || null,
            model,
            version,
            images,
        },
    };
}

async function saveAndRefresh(metadata, message) {
    if (!state.selected) {
        return;
    }
    setBusy(true);
    try {
        await saveMetadata(state.selected.file_path, metadata);
        const selectedPath = state.selected.file_path;
        await loadLoras({ quiet: true });
        selectItem(selectedPath);
        toast(message, "success");
    } catch (error) {
        toast(error.message, "error");
    } finally {
        setBusy(false);
    }
}

function parseVersionId(value) {
    const text = value.trim();
    if (/^\d+$/.test(text)) {
        return Number(text);
    }
    try {
        const url = new URL(text);
        const explicit = url.searchParams.get("modelVersionId");
        if (explicit && /^\d+$/.test(explicit)) {
            return Number(explicit);
        }
        const downloadMatch = url.pathname.match(/\/models\/(\d+)/);
        if (url.pathname.includes("/api/download/models/") && downloadMatch) {
            return Number(downloadMatch[1]);
        }
    } catch {
        return null;
    }
    return null;
}

async function submitDownload(event) {
    event.preventDefault();
    const modelVersionId = parseVersionId(els.downloadInput.value);
    if (!modelVersionId) {
        toast("请输入 modelVersionId，或带 modelVersionId 参数的 Civitai 链接", "error");
        return;
    }

    setBusy(true, "正在下载 LoRA...");
    try {
        await downloadLora({
            modelVersionId,
            saveRoot: els.downloadRoot.value,
            relativeDir: els.downloadSubdir.value.trim(),
        });
        els.downloadDrawer.hidden = true;
        els.downloadInput.value = "";
        await loadLoras({ quiet: true });
        toast("下载完成", "success");
    } catch (error) {
        toast(error.message, "error");
    } finally {
        setBusy(false);
    }
}

async function loadRoots() {
    const result = await fetchRoots();
    state.roots = result.roots || [];
    renderRoots();
}

async function loadLoras({ quiet = false } = {}) {
    if (!quiet) {
        setBusy(true, "正在扫描本地 LoRA...");
    }
    try {
        const result = await fetchLoras();
        state.items = result.items || [];
        renderGrid();
        if (state.selected) {
            state.selected = state.items.find((item) => item.file_path === state.selected.file_path) || null;
            renderDetails();
        }
    } catch (error) {
        toast(error.message, "error");
    } finally {
        setBusy(false);
    }
}

function setBusy(isBusy, message = "") {
    els.refreshBtn.disabled = isBusy;
    els.downloadPanelBtn.disabled = isBusy;
    if (message) {
        els.summary.textContent = message;
    }
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

function bindEvents() {
    els.refreshBtn.addEventListener("click", () => loadLoras());
    els.searchInput.addEventListener("input", () => {
        state.search = els.searchInput.value;
        renderGrid();
    });
    els.rootFilter.addEventListener("change", () => {
        state.root = els.rootFilter.value;
        renderGrid();
    });
    els.downloadPanelBtn.addEventListener("click", () => {
        els.downloadDrawer.hidden = false;
        els.downloadInput.focus();
    });
    els.closeDownloadBtn.addEventListener("click", () => {
        els.downloadDrawer.hidden = true;
    });
    els.downloadDrawer.addEventListener("click", (event) => {
        if (event.target === els.downloadDrawer) {
            els.downloadDrawer.hidden = true;
        }
    });
    els.downloadForm.addEventListener("submit", submitDownload);
}

async function init() {
    bindEvents();
    try {
        await loadRoots();
        await loadLoras();
    } catch (error) {
        toast(error.message, "error");
        setBusy(false);
    }
}

init();
