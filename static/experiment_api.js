const BASE = "/api/lora-lite/experiments";

async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || `Request failed: ${response.status}`);
    }
    return payload;
}

export async function previewExperiment(recipe) {
    return readJson(await fetch(`${BASE}/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe }),
    }));
}

export async function createExperimentRun(recipe, { submit = true } = {}) {
    return readJson(await fetch(`${BASE}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe, submit }),
    }));
}

export async function fetchExperimentRuns({ limit = 50 } = {}) {
    const params = new URLSearchParams({ limit });
    return readJson(await fetch(`${BASE}/runs?${params}`));
}

export async function fetchExperimentRun(runId) {
    return readJson(await fetch(`${BASE}/runs/${encodeURIComponent(runId)}`));
}

export async function refreshExperimentRun(runId) {
    return readJson(await fetch(`${BASE}/runs/${encodeURIComponent(runId)}/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
    }));
}
