/**
 * 重复文件检测清理工具 - 前端交互逻辑
 */

// ───────── 认证：401 自动跳转登录 ─────────
const _origFetch = window.fetch;
window.fetch = async function(...args) {
    const resp = await _origFetch.apply(this, args);
    if (resp.status === 401) {
        window.location.href = '/login';
        throw new Error('未授权，请重新登录');
    }
    return resp;
};

// ───────── DOM 引用 ─────────
const $ = (sel, ctx) => (ctx || document).querySelector(sel);
const $$ = (sel, ctx) => (ctx || document).querySelectorAll(sel);

const folderInput = $("#folder-input");
const pathDropdown = $("#path-dropdown");
const btnBrowse = $("#btn-browse");
const btnScan = $("#btn-scan");
const optAutoScan = $("#opt-auto-scan");
const optRecursive = $("#opt-recursive");
const optSkipEmpty = $("#opt-skip-empty");
const keepRuleSelect = $("#keep-rule");
const progressArea = $("#progress-area");
const progressFill = $("#progress-fill");
const progressText = $("#progress-text");
const btnStop = $("#btn-stop");
const btnPause = $("#btn-pause");
const allFilesContainer = $("#all-files-container");
const dupResultsContainer = $("#dup-results-container");
const leftPlaceholder = $("#left-placeholder");
const rightPlaceholder = $("#right-placeholder");
const leftFileList = $("#left-file-list");
const rightFileList = $("#right-file-list");
const leftColHeaders = $("#left-col-headers");
const rightColHeaders = $("#right-col-headers");
const fileCount = $("#file-count");
const hashStats = $("#hash-stats");
const hashFilter = $("#hash-filter");
const dupCount = $("#dup-count");
const summaryText = $("#summary-text");
const btnRescan = $("#btn-rescan");
const btnDelete = $("#btn-delete");
const confirmModal = $("#confirm-modal");
const confirmBody = $("#confirm-body");
const btnCancel = $("#btn-cancel");
const btnConfirm = $("#btn-confirm");
const contextMenu = $("#context-menu");
const toast = $("#toast");
const loadingOverlay = $("#loading-overlay");
const hoverTooltip = $("#hover-tooltip");
const paginationBar = $("#pagination-bar");
const btnPrevPage = $("#btn-prev-page");
const btnNextPage = $("#btn-next-page");
const pageInfo = $("#page-info");
const rightPaginationBar = $("#right-pagination-bar");
const btnDupPrevPage = $("#btn-dup-prev-page");
const btnDupNextPage = $("#btn-dup-next-page");
const dupPageInfo = $("#dup-page-info");

// ───────── 状态 ─────────
let scanId = null;
let scanData = null;       // 来自 /api/scan/<id>/details 的完整数据
let ctxFilePath = null;    // 右键目标路径
let toastTimer = null;
let _allFiles = [];        // 所有文件的完整数据（内存中维护）
let _currentPage = 1;      // 当前页码（从 1 开始）
const _pageSize = 100;     // 每页显示文件数
let _currentPhaseMsg = ""; // 当前阶段文字（用于进度显示，避免累积）
let _dupCurrentPage = 1;   // 重复组当前页码
const _dupPageSize = 50;   // 重复组每页显示数
let _hashSuccessCount = 0; // Hash 成功文件数
let _hashFailCount = 0;    // Hash 失败文件数
let _hashFilterValue = "all"; // Hash 筛选：all / success / fail

// 列宽（持久化，扫描后不重置）
const colWidths = {
    left: parseInt(localStorage.getItem("dupfinder_colw_left") || "200", 10),
    right: parseInt(localStorage.getItem("dupfinder_colw_right") || "180", 10),
};

// ───────── Toast ─────────
function showToast(msg, duration = 2500) {
    toast.textContent = msg;
    toast.style.display = "block";
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.style.display = "none"; }, duration);
}

// ───────── 悬浮提示 ─────────
function initHoverTooltip() {
    document.addEventListener("mouseover", (e) => {
        const target = e.target.closest(".f-name, .f-path");
        if (!target) { hideTooltip(); return; }
        const text = target._fullText || target.textContent;
        if (!text || target.scrollWidth <= target.clientWidth + 2) {
            hideTooltip();
            return;
        }
        hoverTooltip.textContent = text;
        hoverTooltip.style.display = "block";
        moveTooltip(e);
    });

    document.addEventListener("mousemove", (e) => {
        if (hoverTooltip.style.display === "block") {
            moveTooltip(e);
        }
    });

    document.addEventListener("mouseout", (e) => {
        const target = e.target.closest(".f-name, .f-path");
        if (target && !target.contains(e.relatedTarget)) {
            hideTooltip();
        }
    });
}

function moveTooltip(e) {
    let x = e.clientX + 14;
    let y = e.clientY + 14;
    // 防止溢出窗口右侧
    const tw = hoverTooltip.offsetWidth;
    if (x + tw > window.innerWidth - 10) x = window.innerWidth - tw - 10;
    // 防止溢出窗口底部
    const th = hoverTooltip.offsetHeight;
    if (y + th > window.innerHeight - 10) y = e.clientY - th - 8;
    hoverTooltip.style.left = x + "px";
    hoverTooltip.style.top = y + "px";
}

function hideTooltip() {
    hoverTooltip.style.display = "none";
}
initHoverTooltip();

// ───────── 列宽拖拽 ─────────
let resizeState = null; // { panel, startX, startWidth, handle }

function initColumnResize() {
    document.addEventListener("mousedown", (e) => {
        const handle = e.target.closest(".col-h-handle");
        if (!handle) return;
        const panel = handle.dataset.panel;
        resizeState = {
            panel,
            startX: e.clientX,
            startWidth: colWidths[panel],
            handle,
        };
        handle.classList.add("dragging");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
        if (!resizeState) return;
        const dx = e.clientX - resizeState.startX;
        // 向右拖=缩小路径列，向左拖=放大路径列（因为路径列在右侧）
        const newWidth = Math.max(60, Math.min(600, resizeState.startWidth - dx));
        colWidths[resizeState.panel] = newWidth;
        applyColumnWidths(resizeState.panel);
    });

    document.addEventListener("mouseup", () => {
        if (!resizeState) return;
        resizeState.handle.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        localStorage.setItem("dupfinder_colw_left", colWidths.left);
        localStorage.setItem("dupfinder_colw_right", colWidths.right);
        resizeState = null;
    });
}

function applyColumnWidths(panel) {
    const w = colWidths[panel];
    // 更新列头
    const hdr = panel === "left" ? leftColHeaders : rightColHeaders;
    const hPath = hdr.querySelector(".col-h-path");
    if (hPath) hPath.style.width = w + "px";

    // 更新该面板内所有行的 .f-path
    const list = panel === "left" ? leftFileList : rightFileList;
    const paths = list.querySelectorAll(".f-path");
    paths.forEach(p => { p.style.width = w + "px"; });
}

function applyAllColumnWidths() {
    applyColumnWidths("left");
    applyColumnWidths("right");
}
initColumnResize();

// ───────── 路径浏览 ─────────
let browsePath = "";
let browseDebounceTimer = null;

async function browseDir() {
    try {
        const resp = await fetch("/api/browse", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: browsePath }),
        });
        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            const errMsg = errData.error || resp.statusText || `HTTP ${resp.status}`;
            console.error("[browseDir] API 返回错误:", errMsg);
            showToast("浏览目录失败: " + errMsg);
            return;
        }
        const data = await resp.json();
        if (data.error) {
            console.error("[browseDir] 服务端错误:", data.error);
            showToast("浏览目录失败: " + data.error);
            return;
        }
        console.log("[browseDir] 成功获取目录列表:", data.path, "条目数:", data.entries?.length || 0);
        browsePath = data.path;
        renderDropdown(data.entries || [], data.path);
    } catch (e) {
        console.error("[browseDir] 异常:", e);
        showToast("浏览目录失败: " + e.message);
    }
}

function renderDropdown(entries, currentPath) {
    pathDropdown.innerHTML = "";

    if (currentPath && currentPath !== "" && currentPath !== "/") {
        const parent = document.createElement("div");
        parent.className = "path-item";
        parent.innerHTML = '<span class="icon">📂</span> .. (上级目录)';
        parent.addEventListener("click", () => {
            if (currentPath.includes(":\\") || currentPath.includes(":/")) {
                // Windows 路径：去掉末尾分隔符后找最后一个分隔符
                const parentPath = currentPath.replace(/[\\\/]$/, "");
                const lastSep = Math.max(parentPath.lastIndexOf("\\"), parentPath.lastIndexOf("/"));
                if (lastSep < 0) {
                    // "C:" 这种无分隔符形式，回到盘符列表
                    browsePath = "";
                } else if (lastSep <= 2) {
                    // "C:\foo" → 上级是 "C:\"
                    browsePath = parentPath.substring(0, lastSep) + "\\";
                } else {
                    browsePath = parentPath.substring(0, lastSep);
                }
            } else {
                browsePath = currentPath.split("/").slice(0, -1).join("/") || "/";
            }
            browseDir();
        });
        pathDropdown.appendChild(parent);
    }

    entries.forEach(e => {
        const div = document.createElement("div");
        div.className = "path-item";
        div.innerHTML = `<span class="icon">📁</span> ${escapeHtml(e.name)}`;
        div.addEventListener("click", () => {
            folderInput.value = e.path;
            pathDropdown.style.display = "none";
            folderInput.dispatchEvent(new Event("change"));
        });
        pathDropdown.appendChild(div);
    });
    pathDropdown.style.display = "block";
}

btnBrowse.addEventListener("click", () => {
    const val = folderInput.value.trim();
    if (val) browsePath = val;
    browseDir();
});

folderInput.addEventListener("focus", () => {
    const val = folderInput.value.trim();
    if (val) { browsePath = val; browseDir(); }
});

folderInput.addEventListener("input", () => {
    clearTimeout(browseDebounceTimer);
    browseDebounceTimer = setTimeout(() => {
        const val = folderInput.value.trim();
        if (val) { browsePath = val; browseDir(); }
    }, 500);
});

document.addEventListener("click", (e) => {
    if (!pathDropdown.contains(e.target) && e.target !== folderInput && e.target !== btnBrowse) {
        pathDropdown.style.display = "none";
    }
});

// ───────── 右键菜单 ─────────
function showContextMenu(e, filepath) {
    ctxFilePath = filepath;
    contextMenu.style.display = "block";
    const x = Math.min(e.clientX, window.innerWidth - 200);
    const y = Math.min(e.clientY, window.innerHeight - 160);
    contextMenu.style.left = x + "px";
    contextMenu.style.top = y + "px";
    e.preventDefault();
}

document.addEventListener("click", () => { contextMenu.style.display = "none"; });

// 绑定所有右键菜单项点击
$$(".ctx-item").forEach(item => {
    item.addEventListener("click", async () => {
        const action = item.dataset.action;
        if (!ctxFilePath) return;
        contextMenu.style.display = "none";

        if (action === "open") {
            await fetch("/api/open", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: ctxFilePath }),
            });
        } else if (action === "open-folder") {
            await fetch("/api/open-folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: ctxFilePath }),
            });
        } else if (action === "copy-path") {
            await copyToClipboard(ctxFilePath, "文件路径");
        } else if (action === "copy-folder-path") {
            // 提取文件所在目录路径
            const folderPath = ctxFilePath.replace(/\\/g, "/");
            const lastSlash = folderPath.lastIndexOf("/");
            const dir = lastSlash > 0 ? folderPath.substring(0, lastSlash) : folderPath;
            await copyToClipboard(dir, "文件夹路径");
        }
    });
});

/**
 * 将文本复制到系统剪贴板，并弹出 Toast 提示
 */
async function copyToClipboard(text, label) {
    try {
        // 优先使用现代 API
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            // 回退方案：创建临时 textarea
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            ta.style.top = "-9999px";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
        }
        showToast(`${label}已复制到剪贴板`);
    } catch (e) {
        showToast(`复制失败：${e.message}`);
    }
}

// ───────── 扫描流 ─────────
btnScan.addEventListener("click", startScan);
btnRescan.addEventListener("click", startScan);

async function startScan() {
    const folder = folderInput.value.trim();
    if (!folder) {
        showToast("请输入文件夹路径");
        return;
    }

    resetUI();
    btnScan.disabled = true;
    btnRescan.disabled = true;
    btnStop.disabled = false;
    btnPause.disabled = false;
    btnPause.textContent = "⏸ 暂停";
    progressArea.style.display = "block";
    progressFill.style.width = "0%";
    progressText.textContent = "正在连接…";
    progressText.style.color = "";

    try {
        const resp = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                folder: folder,
                recursive: optRecursive.checked,
                skip_empty: optSkipEmpty.checked,
                keep_rule: keepRuleSelect.value,
            }),
        });
        const data = await resp.json();
        if (data.error) {
            showToast(data.error);
            btnScan.disabled = false;
            return;
        }
        scanId = data.scan_id;
        listenProgress(scanId);
    } catch (e) {
        showToast("启动扫描失败：" + e.message);
        btnScan.disabled = false;
        progressArea.style.display = "none";
    }
}

let currentEventSource = null;

function listenProgress(sid) {
    const evtSource = new EventSource(`/api/scan/${sid}/progress`);
    currentEventSource = evtSource;

    evtSource.addEventListener("message", (e) => {
        try {
            const msg = JSON.parse(e.data);
            if (msg.type === "error") {
                handleScanError(msg.message);
                evtSource.close();
                currentEventSource = null;
                btnScan.disabled = false;
                return;
            }
            if (msg.type === "cancelled") {
                handleScanCancelled();
                evtSource.close();
                currentEventSource = null;
                return;
            }
            handleProgress(msg);
            if (msg.type === "done") {
                evtSource.close();
                currentEventSource = null;
                btnPause.disabled = true;
                btnStop.disabled = true;
                onScanComplete(sid);
            }
        } catch (_) {}
    });

    evtSource.addEventListener("error", () => {
        evtSource.close();
        currentEventSource = null;
        btnScan.disabled = false;
    });
}

function handleProgress(msg) {
    switch (msg.type) {
        case "phase":
            _currentPhaseMsg = msg.message;
            progressText.textContent = msg.message;
            if (msg.file_count !== undefined) {
                fileCount.textContent = `共 ${msg.file_count} 个文件`;
            }
            break;
        case "progress":
            progressFill.style.width = msg.progress + "%";
            // 替换而非追加，避免文字不断累积
            if (msg.total_files && msg.current_files !== undefined) {
                progressText.textContent = `${_currentPhaseMsg} ${msg.progress}%  ${msg.current_files}/${msg.total_files}`;
            } else if (msg.current && msg.total) {
                progressText.textContent = `${_currentPhaseMsg} ${msg.progress}%  ${msg.current} / ${msg.total}`;
            }
            break;
        case "files_update":
            // 增量更新文件列表
            if (msg.files && msg.files.length > 0) {
                appendFilesToList(msg.files);
            }
            break;
        case "paused":
            progressText.textContent = "⏸ 扫描已暂停";
            progressText.style.color = "#f39c12";
            btnPause.textContent = "▶ 继续";
            break;
        case "resumed":
            progressText.style.color = "";
            btnPause.disabled = false;
            btnPause.textContent = "⏸ 暂停";
            break;
        case "done":
            if (msg.duplicate_count > 0) progressFill.style.width = "100%";
            progressText.textContent = msg.message;
            summaryText.textContent = msg.duplicate_count > 0
                ? `将删除 ${msg.duplicate_count} 个文件，释放 ${msg.space_saved} 空间`
                : "";
            btnScan.disabled = false;
            btnRescan.disabled = false;
            btnPause.disabled = true;
            btnPause.textContent = "⏸ 暂停";
            btnStop.disabled = true;
            scanId = null;
            break;
        case "ping": break;
    }
}

function handleScanError(message) {
    progressText.textContent = "扫描出错";
    progressText.style.color = "#f44747";
    summaryText.textContent = message;
    summaryText.style.color = "#f44747";
    btnScan.disabled = false;
    btnRescan.disabled = false;
    btnPause.disabled = true;
    btnStop.disabled = true;
    scanId = null;
}

function handleScanCancelled() {
    progressText.textContent = "扫描已停止";
    progressText.style.color = "#e67e22";
    summaryText.textContent = "";
    btnScan.disabled = false;
    btnRescan.disabled = false;
    btnPause.disabled = true;
    btnStop.disabled = true;
    scanId = null;
}

// ───────── 停止扫描 ─────────
btnStop.addEventListener("click", async () => {
    if (!scanId) return;
    btnStop.disabled = true;
    btnPause.disabled = true;
    try {
        await fetch(`/api/scan/${scanId}/stop`, { method: "POST" });
    } catch (e) {
        // 即使请求失败也关闭 SSE
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }
        btnScan.disabled = false;
    }
});

// ───────── 暂停/继续扫描 ─────────
btnPause.addEventListener("click", async () => {
    if (!scanId) return;
    btnPause.disabled = true;
    try {
        const resp = await fetch(`/api/scan/${scanId}/pause`, { method: "POST" });
        const data = await resp.json();
        if (data.error) {
            showToast(data.error);
        }
    } catch (e) {
        showToast("操作失败：" + e.message);
    } finally {
        btnPause.disabled = false;
    }
});

// ───────── 自动扫描 ─────────
let autoScanEnabled = localStorage.getItem("autoScan") === "1";
optAutoScan.checked = autoScanEnabled;

optAutoScan.addEventListener("change", () => {
    autoScanEnabled = optAutoScan.checked;
    localStorage.setItem("autoScan", autoScanEnabled ? "1" : "0");
    if (autoScanEnabled) {
        showToast("自动扫描已开启：选择文件夹后自动开始");
        const folder = folderInput.value.trim();
        if (folder && !scanId) startScan();
    } else {
        showToast("自动扫描已关闭");
    }
});

// 自动扫描模式下，选择文件夹后自动触发
folderInput.addEventListener("change", () => {
    if (autoScanEnabled && folderInput.value.trim() && !scanId) {
        startScan();
    }
});

async function onScanComplete(sid) {
    try {
        const resp = await fetch(`/api/scan/${sid}/details`);
        scanData = await resp.json();

        if (_allFiles.length > 0) {
            // 已有增量数据，更新 _allFiles 中每条记录的状态和相对路径
            const fileMap = {};
            scanData.all_files.forEach(f => { fileMap[f.path] = f; });

            _allFiles.forEach(f => {
                const server = fileMap[f.path];
                if (server) {
                    f.status = server.status;
                    f.rel = server.rel;
                    f.size_str = server.size_str;
                    f.name = server.name;
                }
            });

            // 补充增量阶段遗漏的文件（如 SSE 断连、hash失败未发送等）
            const existingPaths = new Set(_allFiles.map(f => f.path));
            let added = 0;
            scanData.all_files.forEach(f => {
                if (!existingPaths.has(f.path)) {
                    _allFiles.push({
                        path: f.path,
                        name: f.name,
                        size: f.size,
                        size_str: f.size_str,
                        rel: f.rel,
                        status: f.status || "normal",
                    });
                    added++;
                }
            });
        } else if (scanData.all_files && scanData.all_files.length > 0) {
            // 没有增量数据（如恢复上次扫描），从服务端数据填充 _allFiles
            _allFiles = scanData.all_files.map(f => ({
                path: f.path,
                name: f.name,
                size: f.size,
                size_str: f.size_str,
                rel: f.rel,
                status: f.status || "normal",
            }));
            leftPlaceholder.style.display = "none";
            leftColHeaders.style.display = "flex";
            paginationBar.style.display = "flex";
        }

        // 重新计算 hash 成功/失败数量
        _hashSuccessCount = 0;
        _hashFailCount = 0;
        _allFiles.forEach(f => {
            if (f.status === "hash_error") _hashFailCount++;
            else _hashSuccessCount++;
        });

        // 显示筛选框并更新计数
        hashFilter.style.display = "inline-block";
        _updateFileCountDisplay();

        renderCurrentPage();
        renderDuplicateGroups(scanData.duplicate_groups);

        if (scanData.total_groups === 0) {
            rightPlaceholder.style.display = "block";
            rightColHeaders.style.display = "none";
            rightPlaceholder.textContent = "✓  没有发现重复文件";
            rightPlaceholder.style.color = "#27ae60";
            rightPlaceholder.style.fontSize = "16px";
        } else {
            rightPlaceholder.style.display = "none";
            rightColHeaders.style.display = "flex";
            dupCount.textContent = `${scanData.total_groups} 组重复`;
            btnDelete.disabled = false;
        }
    } catch (e) {
        showToast("获取扫描详情失败");
    }
}

function resetUI() {
    _allFiles = [];
    _currentPage = 1;
    _allDupGroups = [];
    _dupCurrentPage = 1;
    _hashSuccessCount = 0;
    _hashFailCount = 0;
    _hashFilterValue = "all";
    hashFilter.value = "all";
    hashFilter.style.display = "none";
    hashStats.innerHTML = "";
    leftPlaceholder.style.display = "none";
    rightPlaceholder.style.display = "block";
    rightPlaceholder.textContent = "扫描结果将显示在这里";
    rightPlaceholder.style.color = "#bbb";
    rightPlaceholder.style.fontSize = "14px";
    leftFileList.innerHTML = "";
    rightFileList.innerHTML = "";
    leftColHeaders.style.display = "none";
    rightColHeaders.style.display = "none";
    paginationBar.style.display = "none";
    rightPaginationBar.style.display = "none";
    fileCount.textContent = "共 0 个文件";
    dupCount.textContent = "";
    summaryText.textContent = "";
    summaryText.style.color = "";
    btnDelete.disabled = true;
    scanData = null;
}

// ───────── 格式化文件大小 ─────────
function formatFileSize(bytes) {
    if (bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let val = bytes;
    for (let i = 0; i < units.length; i++) {
        if (val < 1024) return val.toFixed(1) + " " + units[i];
        val /= 1024;
    }
    return val.toFixed(1) + " PB";
}

// ───────── 增量追加文件到内存列表 ─────────
function appendFilesToList(files) {
    const isFirst = _allFiles.length === 0;

    files.forEach(f => {
        const parts = f.path.replace(/\\/g, "/").split("/");
        const fileName = parts[parts.length - 1] || f.path;
        const parentDir = parts.length > 1 ? parts[parts.length - 2] : "";
        const isHashError = f.status === "hash_error";
        _allFiles.push({
            path: f.path,
            name: fileName,
            size: f.size,
            size_str: formatFileSize(f.size),
            rel: parentDir,  // 增量阶段先显示父目录，扫描完成后更新为完整相对路径
            status: isHashError ? "hash_error" : "normal",
        });
        if (isHashError) _hashFailCount++;
        else _hashSuccessCount++;
    });

    // 首次增量更新时显示列头、隐藏占位符、显示分页栏和筛选框
    if (isFirst) {
        leftPlaceholder.style.display = "none";
        leftColHeaders.style.display = "flex";
        paginationBar.style.display = "flex";
        hashFilter.style.display = "inline-block";
    }

    // 更新文件计数和 hash 统计
    _updateFileCountDisplay();

    // 如果新增文件落在当前页或之前的页，重新渲染当前页
    renderCurrentPage();
}

// ───────── 更新文件计数和 hash 统计显示 ─────────
function _updateFileCountDisplay() {
    fileCount.textContent = `共 ${_allFiles.length} 个文件`;
    if (_hashFailCount > 0 || _hashSuccessCount > 0) {
        hashStats.innerHTML = `Hash 成功：<span class="hash-ok">${_hashSuccessCount}</span>，Hash 失败：<span class="hash-fail">${_hashFailCount}</span>`;
    } else {
        hashStats.innerHTML = "";
    }
}

// ───────── 渲染当前页文件列表 ─────────
function renderCurrentPage() {
    // 根据 hash 筛选
    let filteredFiles = _allFiles;
    if (_hashFilterValue === "success") {
        filteredFiles = _allFiles.filter(f => f.status !== "hash_error");
    } else if (_hashFilterValue === "fail") {
        filteredFiles = _allFiles.filter(f => f.status === "hash_error");
    }

    const totalPages = Math.max(1, Math.ceil(filteredFiles.length / _pageSize));
    if (_currentPage > totalPages) _currentPage = totalPages;

    const start = (_currentPage - 1) * _pageSize;
    const end = Math.min(start + _pageSize, filteredFiles.length);
    const pageFiles = filteredFiles.slice(start, end);

    leftFileList.innerHTML = "";

    if (pageFiles.length > 0) {
        const fragment = document.createDocumentFragment();
        pageFiles.forEach(f => {
            const row = document.createElement("div");
            row.className = "file-row";
            if (f.status === "dup") row.classList.add("dup-row");
            if (f.status === "keep") row.classList.add("keep-row");
            if (f.status === "hash_error") row.classList.add("hash-error-row");

            const nameSpan = document.createElement("span");
            nameSpan.className = "f-name";
            nameSpan._fullText = f.name;
            nameSpan.textContent = f.status === "hash_error" ? "⚠ " + f.name : f.name;

            const sizeSpan = document.createElement("span");
            sizeSpan.className = "f-size";
            sizeSpan.textContent = f.size_str;

            const hashSpan = document.createElement("span");
            hashSpan.className = "f-hash";
            if (f.status === "hash_error") {
                hashSpan.textContent = "失败";
                hashSpan.classList.add("hash-fail");
            } else {
                hashSpan.textContent = "成功";
            }

            const pathSpan = document.createElement("span");
            pathSpan.className = "f-path";
            pathSpan._fullText = f.rel;
            pathSpan.textContent = f.rel;

            row.appendChild(nameSpan);
            row.appendChild(sizeSpan);
            row.appendChild(hashSpan);
            row.appendChild(pathSpan);

            row.addEventListener("contextmenu", (e) => {
                showContextMenu(e, f.path);
            });

            fragment.appendChild(row);
        });
        leftFileList.appendChild(fragment);
    }

    // 更新分页控件
    pageInfo.textContent = `第 ${_currentPage} / ${totalPages} 页`;
    btnPrevPage.disabled = _currentPage <= 1;
    btnNextPage.disabled = _currentPage >= totalPages;

    // 无文件时隐藏分页栏
    if (_allFiles.length === 0) {
        paginationBar.style.display = "none";
    }

    applyColumnWidths("left");
}

// ───────── 分页导航事件 ─────────
btnPrevPage.addEventListener("click", () => {
    if (_currentPage > 1) {
        _currentPage--;
        renderCurrentPage();
    }
});

btnNextPage.addEventListener("click", () => {
    let filteredLen = _allFiles.length;
    if (_hashFilterValue === "success") {
        filteredLen = _allFiles.filter(f => f.status !== "hash_error").length;
    } else if (_hashFilterValue === "fail") {
        filteredLen = _allFiles.filter(f => f.status === "hash_error").length;
    }
    const totalPages = Math.ceil(filteredLen / _pageSize);
    if (_currentPage < totalPages) {
        _currentPage++;
        renderCurrentPage();
    }
});

// ───────── Hash 筛选下拉框 ─────────
hashFilter.addEventListener("change", () => {
    _hashFilterValue = hashFilter.value;
    _currentPage = 1;  // 切换筛选时回到第一页
    renderCurrentPage();
});

// ───────── 渲染右侧重复组（保存数据 + 分页渲染） ─────────
let _allDupGroups = [];  // 所有重复组数据（内存中维护）

function renderDuplicateGroups(groups) {
    _allDupGroups = groups;
    _dupCurrentPage = 1;

    if (groups.length === 0) {
        rightColHeaders.style.display = "none";
        rightPaginationBar.style.display = "none";
        rightFileList.innerHTML = "";
        return;
    }

    rightColHeaders.style.display = "flex";
    rightPaginationBar.style.display = "flex";
    renderCurrentDupPage();
}

// ───────── 渲染当前页重复组 ────────
function renderCurrentDupPage() {
    const totalPages = Math.max(1, Math.ceil(_allDupGroups.length / _dupPageSize));
    if (_dupCurrentPage > totalPages) _dupCurrentPage = totalPages;

    const start = (_dupCurrentPage - 1) * _dupPageSize;
    const end = Math.min(start + _dupPageSize, _allDupGroups.length);
    const pageGroups = _allDupGroups.slice(start, end);

    rightFileList.innerHTML = "";

    const isManual = scanData && scanData.keep_rule === "manual";

    pageGroups.forEach(g => {
        const groupDiv = document.createElement("div");
        groupDiv.className = "dup-group";

        const hdr = document.createElement("div");
        hdr.className = "group-header";
        hdr.innerHTML = `
            <span class="g-idx">第 ${g.index} 组</span>
            <span class="g-stat">${g.count} 个相同文件</span>
            <span class="g-stat">单个大小 ${g.file_size_str}</span>
            <span class="g-stat">可释放 ${g.space_saved_str}</span>
        `;
        groupDiv.appendChild(hdr);

        g.files.forEach(f => {
            const row = document.createElement("div");
            row.className = "dup-file-row";
            row.dataset.path = f.path;
            row.dataset.keep = f.is_keep ? "1" : "0";

            const isDelete = isManual ? false : !f.is_keep;
            if (isDelete) row.classList.add("delete-row");
            if (f.is_keep && !isManual) row.classList.add("keep-row");

            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = isDelete;
            cb.addEventListener("change", () => {
                if (cb.checked) {
                    row.classList.add("delete-row");
                    if (!isManual) row.classList.remove("keep-row");
                } else {
                    row.classList.remove("delete-row");
                    if (!isManual) row.classList.add("keep-row");
                }
                updateDeleteSummary();
            });

            const nameSpan = document.createElement("span");
            nameSpan.className = "f-name";
            nameSpan._fullText = f.name;
            nameSpan.textContent = f.name;

            const sizeSpan = document.createElement("span");
            sizeSpan.className = "f-size";
            sizeSpan.textContent = f.size_str;

            const hashSpan = document.createElement("span");
            hashSpan.className = "f-hash";
            hashSpan.textContent = "成功";

            const pathSpan = document.createElement("span");
            pathSpan.className = "f-path";
            pathSpan._fullText = f.rel;
            pathSpan.textContent = f.rel;

            row.appendChild(cb);
            row.appendChild(nameSpan);
            row.appendChild(sizeSpan);
            row.appendChild(hashSpan);
            row.appendChild(pathSpan);

            row.addEventListener("contextmenu", (e) => {
                showContextMenu(e, f.path);
            });

            row.addEventListener("click", (e) => {
                if (e.target !== cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event("change"));
                }
            });

            groupDiv.appendChild(row);
        });

        const sep = document.createElement("div");
        sep.style.cssText = "height:2px;background:#e0e4ea;margin:0 6px;";
        groupDiv.appendChild(sep);

        rightFileList.appendChild(groupDiv);
    });

    // 更新分页控件
    dupPageInfo.textContent = `第 ${_dupCurrentPage} / ${totalPages} 页`;
    btnDupPrevPage.disabled = _dupCurrentPage <= 1;
    btnDupNextPage.disabled = _dupCurrentPage >= totalPages;

    applyColumnWidths("right");
    updateDeleteSummary();
}

// ───────── 重复组翻页事件 ─────────
btnDupPrevPage.addEventListener("click", () => {
    if (_dupCurrentPage > 1) {
        _dupCurrentPage--;
        renderCurrentDupPage();
    }
});

btnDupNextPage.addEventListener("click", () => {
    const totalPages = Math.ceil(_allDupGroups.length / _dupPageSize);
    if (_dupCurrentPage < totalPages) {
        _dupCurrentPage++;
        renderCurrentDupPage();
    }
});

function updateDeleteSummary() {
    if (!scanData) return;
    let count = 0;
    let totalSize = 0;
    $$(".dup-file-row", rightFileList).forEach(row => {
        const cb = $("input[type=checkbox]", row);
        if (cb && cb.checked && row.dataset.keep !== "1") {
            count++;
            const f = scanData.duplicate_groups
                .flatMap(g => g.files)
                .find(x => x.path === row.dataset.path);
            if (f) totalSize += f.size;
        }
    });

    function fmt(sz) {
        if (sz === 0) return "0 B";
        const u = ["B", "KB", "MB", "GB", "TB"];
        let v = sz;
        for (let i = 0; i < u.length; i++) {
            if (v < 1024) return v.toFixed(1) + " " + u[i];
            v /= 1024;
        }
        return v.toFixed(1) + " PB";
    }

    summaryText.textContent = count > 0
        ? `将删除 ${count} 个文件，释放 ${fmt(totalSize)} 空间`
        : "未选中任何文件";
}

// ───────── 删除确认 ─────────
btnDelete.addEventListener("click", () => {
    const selected = [];
    $$(".dup-file-row", rightFileList).forEach(row => {
        const cb = $("input[type=checkbox]", row);
        if (cb && cb.checked && row.dataset.keep !== "1") {
            selected.push(row.dataset.path);
        }
    });

    if (selected.length === 0) {
        showToast("当前没有选中任何要删除的文件");
        return;
    }

    let totalSize = 0;
    const fileList = selected.map(fp => {
        const f = scanData.duplicate_groups
            .flatMap(g => g.files)
            .find(x => x.path === fp);
        if (f) totalSize += f.size;
        return fp;
    });

    function fmt(sz) {
        if (sz === 0) return "0 B";
        const u = ["B", "KB", "MB", "GB", "TB"];
        let v = sz;
        for (let i = 0; i < u.length; i++) {
            if (v < 1024) return v.toFixed(1) + " " + u[i];
            v /= 1024;
        }
        return v.toFixed(1) + " PB";
    }

    let bodyText = `确定要删除以下 ${selected.length} 个文件吗？\n将释放 ${fmt(totalSize)} 磁盘空间\n\n`;
    const showFiles = fileList.slice(0, 15).map(fp => {
        const parts = fp.replace(/\\/g, "/").split("/");
        return "  • " + parts[parts.length - 1];
    });
    bodyText += showFiles.join("\n");
    if (fileList.length > 15) {
        bodyText += `\n  … 等共 ${fileList.length} 个文件`;
    }
    bodyText += "\n\n⚠ 此操作不可撤销！";

    confirmBody.textContent = bodyText;
    confirmModal.style.display = "flex";
    confirmModal._selectedFiles = fileList;
});

btnCancel.addEventListener("click", () => {
    confirmModal.style.display = "none";
});

btnConfirm.addEventListener("click", async () => {
    const files = confirmModal._selectedFiles;
    if (!files || files.length === 0) return;

    confirmModal.style.display = "none";
    loadingOverlay.style.display = "flex";

    try {
        const resp = await fetch("/api/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files: files }),
        });
        const result = await resp.json();
        loadingOverlay.style.display = "none";

        if (result.errors && result.errors.length > 0) {
            showToast(`部分删除成功：${result.deleted} 个，失败 ${result.errors.length} 个`, 4000);
        } else {
            showToast(`成功删除 ${result.deleted} 个重复文件！释放 ${result.total_size_str} 空间`);
        }
        startScan();
    } catch (e) {
        loadingOverlay.style.display = "none";
        showToast("删除失败：" + e.message);
    }
});

confirmModal.addEventListener("click", (e) => {
    if (e.target === confirmModal) confirmModal.style.display = "none";
});

// ───────── 键盘快捷键 ─────────
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        confirmModal.style.display = "none";
        contextMenu.style.display = "none";
        pathDropdown.style.display = "none";
    }
    if (e.ctrlKey && e.key === "Enter") {
        startScan();
        e.preventDefault();
    }
});

// ───────── 工具函数 ─────────
function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// ───────── 页面加载：恢复上次扫描状态 ─────────
(async function restoreLastScan() {
    try {
        const resp = await fetch("/api/scan/latest");
        const data = await resp.json();
        if (!data.scan_id) return;

        const status = data.status;
        const paused = data.paused;
        scanId = data.scan_id;
        folderInput.value = data.folder || "";

        // 运行中或暂停：恢复进度条 UI 并重新连接 SSE
        if (status === "running" || status === "paused") {
            progressArea.style.display = "block";
            progressFill.style.width = "0%";
            progressText.textContent = paused ? "⏸ 扫描已暂停" : "正在恢复连接…";
            progressText.style.color = paused ? "#f39c12" : "";
            btnScan.disabled = true;
            btnRescan.disabled = true;
            btnStop.disabled = false;
            btnPause.disabled = false;
            btnPause.textContent = paused ? "▶ 继续" : "⏸ 暂停";
            listenProgress(scanId);
            return;
        }

        // 已停止或出错：显示终止状态
        if (status === "cancelled" || status === "error") {
            progressArea.style.display = "block";
            progressText.textContent = status === "cancelled" ? "扫描已停止" : "扫描出错";
            progressText.style.color = status === "cancelled" ? "#e67e22" : "#f44747";
            btnScan.disabled = false;
            btnRescan.disabled = false;
            btnPause.disabled = true;
            btnStop.disabled = true;
            return;
        }

        // 已完成：拉取详情并渲染结果
        if (status === "done") {
            const detailResp = await fetch(`/api/scan/${data.scan_id}/details`);
            const detail = await detailResp.json();
            if (detail.error) return;

            scanData = detail;

            // 填充 _allFiles 并使用分页渲染
            _allFiles = detail.all_files.map(f => ({
                path: f.path,
                name: f.name,
                size: f.size,
                size_str: f.size_str,
                rel: f.rel,
                status: f.status || "normal",
            }));
            _currentPage = 1;
            leftPlaceholder.style.display = "none";
            leftColHeaders.style.display = "flex";
            paginationBar.style.display = "flex";

            renderCurrentPage();
            renderDuplicateGroups(detail.duplicate_groups);
            fileCount.textContent = `共 ${detail.total_files} 个文件`;

            if (detail.total_groups === 0) {
                rightPlaceholder.style.display = "block";
                rightColHeaders.style.display = "none";
                rightPlaceholder.textContent = "✓  没有发现重复文件";
                rightPlaceholder.style.color = "#27ae60";
                rightPlaceholder.style.fontSize = "16px";
            } else {
                rightPlaceholder.style.display = "none";
                rightColHeaders.style.display = "flex";
                dupCount.textContent = `${detail.total_groups} 组重复`;
                btnDelete.disabled = false;
            }

            btnRescan.disabled = false;
            summaryText.textContent = detail.total_groups > 0
                ? `上次扫描：${detail.total_groups} 组重复`
                : "上次扫描：未发现重复文件";
        }
    } catch (_) {
        // 恢复失败则保持初始状态，静默处理
    }
})();
