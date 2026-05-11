import { app } from "../../scripts/app.js";

const PAGE_PATH = "/lora-lite";
const TOOLTIP = "打开 LoRA Lite Manager";
const MIN_ACTION_BAR_VERSION = [1, 33, 9];

function openManager(event) {
    const url = `${window.location.origin}${PAGE_PATH}`;
    if (event?.shiftKey) {
        window.open(url, "_blank", "width=1180,height=820,resizable=yes,scrollbars=yes");
        return;
    }
    window.open(url, "_blank");
}

function iconSvg() {
    return `
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 5h16v14H4z"></path>
            <path d="M8 16V8"></path>
            <path d="M8 16h7"></path>
            <path d="M14 11h4"></path>
            <path d="M16 9v4"></path>
        </svg>
    `;
}

function parseVersion(value) {
    return String(value || "0.0.0")
        .replace(/^[vV]/, "")
        .split("-")[0]
        .split(".")
        .map((part) => Number.parseInt(part, 10) || 0)
        .concat([0, 0, 0])
        .slice(0, 3);
}

function compareVersion(left, right) {
    for (let index = 0; index < 3; index += 1) {
        if (left[index] > right[index]) {
            return 1;
        }
        if (left[index] < right[index]) {
            return -1;
        }
    }
    return 0;
}

async function supportsActionBarButtons() {
    let version = window.__COMFYUI_FRONTEND_VERSION__;
    if (!version) {
        try {
            const response = await fetch("/system_stats");
            const data = await response.json();
            version = data?.system?.comfyui_frontend_version || data?.system?.required_frontend_version;
        } catch {
            version = "0.0.0";
        }
    }
    return compareVersion(parseVersion(version), MIN_ACTION_BAR_VERSION) >= 0;
}

async function addLegacyButton() {
    const { ComfyButton } = await import("../../scripts/ui/components/button.js");
    const { ComfyButtonGroup } = await import("../../scripts/ui/components/buttonGroup.js");

    const settingsGroup = app.menu?.settingsGroup;
    if (!settingsGroup?.element?.parentElement || document.querySelector(".lora-lite-menu-group")) {
        return false;
    }

    const button = new ComfyButton({
        icon: "lora-lite",
        tooltip: TOOLTIP,
        app,
        enabled: true,
        classList: "comfyui-button comfyui-menu-mobile-collapse primary",
    });
    button.element.setAttribute("aria-label", TOOLTIP);
    button.element.title = TOOLTIP;
    button.element.addEventListener("click", openManager);
    if (button.iconElement) {
        button.iconElement.innerHTML = iconSvg();
    }

    const group = new ComfyButtonGroup(button);
    group.element.classList.add("lora-lite-menu-group");
    settingsGroup.element.before(group.element);
    return true;
}

function waitForLegacyButton(attempt = 0) {
    if (attempt > 120) {
        console.warn("LoRA Lite: unable to attach menu button");
        return;
    }
    addLegacyButton().then((added) => {
        if (!added) {
            requestAnimationFrame(() => waitForLegacyButton(attempt + 1));
        }
    });
}

app.registerExtension({
    name: "LoraLite.TopMenu",
    async setup() {
        if (!(await supportsActionBarButtons())) {
            waitForLegacyButton();
        }
    },
    actionBarButtons: [
        {
            icon: "icon-[mdi--alpha-l-box] size-4",
            tooltip: TOOLTIP,
            onClick: openManager,
        },
    ],
});
