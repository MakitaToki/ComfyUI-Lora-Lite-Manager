const BASE = "/api/lora-lite";

async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || `请求失败：${response.status}`);
    }
    return payload;
}

export async function fetchRoots() {
    return readJson(await fetch(`${BASE}/roots`));
}

export async function fetchLoras() {
    return readJson(await fetch(`${BASE}/loras`));
}

export async function calculateHash(filePath) {
    return readJson(await fetch(`${BASE}/hash`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: filePath }),
    }));
}

export async function fetchCivitaiByHash(sha256) {
    return readJson(await fetch(`${BASE}/civitai/by-hash/${encodeURIComponent(sha256)}`));
}

export async function saveMetadata(filePath, metadata) {
    return readJson(await fetch(`${BASE}/metadata`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: filePath, metadata }),
    }));
}

export async function downloadLora({ modelVersionId, saveRoot, relativeDir }) {
    return readJson(await fetch(`${BASE}/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            model_version_id: modelVersionId,
            save_root: saveRoot,
            relative_dir: relativeDir,
        }),
    }));
}

export function previewUrl(path) {
    if (!path) {
        return "";
    }
    if (/^https?:\/\//i.test(path)) {
        return path;
    }
    return `${BASE}/preview?path=${encodeURIComponent(path)}`;
}
