const BASE = "/api/lora-lite/collection";

async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || `请求失败：${response.status}`);
    }
    return payload;
}

export async function importCivitaiUrl({ url, limit }) {
    return readJson(await fetch(`${BASE}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, limit, cache_images: true }),
    }));
}

export async function fetchArtworks({ query = "", sort = "newest", limit = 60, offset = 0 } = {}) {
    const params = new URLSearchParams({ q: query, sort, limit, offset });
    return readJson(await fetch(`${BASE}/items?${params}`));
}

export async function fetchArtwork(id) {
    return readJson(await fetch(`${BASE}/items/${encodeURIComponent(id)}`));
}

export async function exportSeeds({ query = "", sort = "popular", limit = 100 } = {}) {
    return readJson(await fetch(`${BASE}/export-seeds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, sort, limit }),
    }));
}

export function collectionImageUrl(path) {
    if (!path) {
        return "";
    }
    if (/^https?:\/\//i.test(path)) {
        return path;
    }
    return `${BASE}/image?path=${encodeURIComponent(path)}`;
}

