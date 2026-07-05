#!/usr/bin/env python3
"""
重复文件检测清理工具 Web 版 v0.7.0
使用 Flask + SSE 提供实时扫描进度。

启动方式:
    # Windows
    start.bat
    # 或
    python app.py

    # Linux / macOS
    bash start.sh
    # 或
    python3 app.py

然后浏览器访问 http://localhost:36901

v0.2.0 更新:
    - 右键菜单新增「复制文件路径」「复制文件夹路径」

v0.4.0 更新:
    - 端口可配置（环境变量 DUPFINDER_PORT 或命令行参数）
    - 保留规则改为下拉框：自动保留名称最短/最长文件、手动选择

v0.4.1 更新:
    - 哈希计算进度改为按文件体积显示（如 3.2 GB / 7.0 GB）

v0.6.0 更新:
    - 新增停止扫描功能（进度条右侧停止按钮）
    - 新增暂停/继续扫描功能
    - 新增自动扫描模式（选择文件夹后自动开始扫描，偏好持久化到 localStorage）

v0.7.0 更新:
    - 新增恢复上次扫描结果（重新打开网页自动加载最近一次扫描）

v0.7.1 更新:
    - 两阶段哈希：先 partial hash 快速筛选，仅对疑似重复文件做全量 SHA-256
    - 多线程并行哈希，充分利用多核 CPU 加速大文件库扫描
"""

import os
import sys
import hashlib
import threading
import json
import queue
import subprocess
import time
import webbrowser
import logging
import traceback
import secrets
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
from collections import defaultdict

import yaml
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, redirect, make_response

# ────────────────── 版本 ──────────────────
__version__ = "0.7.1"

# ────────────────── 配置 ──────────────────
DEFAULT_PORT = 36901

# ────────────────── 日志配置 ──────────────────

def _get_log_dir():
    """返回日志目录，优先使用用户目录下专门文件夹"""
    if getattr(sys, 'frozen', False):
        # EXE 模式：放在可执行文件同级 logs 目录
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir

def _setup_logging():
    """配置全局日志：控制台 + 滚动文件"""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, date_format)

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 控制台 handler（INFO 级别）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件 handler（DEBUG 级别，滚动 3MB x 3）
    log_file = os.path.join(_get_log_dir(), "dupfinder.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=3 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # werkzeug 日志降级
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    return logging.getLogger("dupfinder")

logger = _setup_logging()

# ────────────────── PyInstaller 冻结模式资源路径 ──────────────────
def _resource_path(relative):
    """兼容 PyInstaller 打包后的资源路径"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative)

_TEMPLATE_DIR = _resource_path('templates')
_STATIC_DIR = _resource_path('static')

app = Flask(__name__,
            template_folder=_TEMPLATE_DIR,
            static_folder=_STATIC_DIR)

# ────────────────── 配置文件加载 ──────────────────

def _get_base_dir():
    """返回配置文件和日志的基准目录（EXE 模式下为可执行文件所在目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_DEFAULT_CONFIG = """\
# 重复文件检测清理工具 - 配置文件
# 修改后重启服务生效

server:
  # 监听地址（127.0.0.1 仅本机访问，0.0.0.0 允许局域网访问）
  host: "127.0.0.1"
  # 监听端口
  port: 36901
  # 访问密码（留空则无需密码）
  password: "123456"
"""


def _ensure_default_config():
    """如果 config.yaml 不存在，生成默认配置文件"""
    config_path = os.path.join(_get_base_dir(), 'config.yaml')
    if not os.path.isfile(config_path):
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(_DEFAULT_CONFIG)
            logger.info("已生成默认配置文件: %s", config_path)
        except OSError as e:
            logger.warning("无法生成默认配置文件 %s: %s", config_path, e)


def _load_config():
    """从 config.yaml 加载配置，加载失败时返回默认值"""
    config_path = os.path.join(_get_base_dir(), 'config.yaml')
    defaults = {'host': '127.0.0.1', 'port': 36901, 'password': ''}
    if not os.path.isfile(config_path):
        return defaults
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        server = data.get('server', {}) if data else {}
        return {
            'host': str(server.get('host', '127.0.0.1')).strip(),
            'port': int(server.get('port', 36901)),
            'password': str(server.get('password', '')).strip(),
        }
    except Exception as e:
        logger.error("读取配置文件失败: %s，使用默认配置", e)
        return defaults


# 启动时确保配置文件存在，并加载
_ensure_default_config()
_config = _load_config()

# ────────────────── 会话认证 ──────────────────

_session_token = secrets.token_hex(32)
AUTH_COOKIE = 'dupfinder_session'


def require_auth(f):
    """路由装饰器：校验会话 Cookie，未认证时返回 401；未设置密码时直接放行"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not _config.get('password'):
            return f(*args, **kwargs)
        token = request.cookies.get(AUTH_COOKIE)
        if not secrets.compare_digest(token or '', _session_token):
            if request.is_json:
                return jsonify({'error': '未授权'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


# ────────────────── 全局状态 ──────────────────

# 扫描会话存储: scan_id -> dict
_sessions = {}
_session_lock = threading.Lock()
_scan_counter = 0


def _new_scan_id():
    global _scan_counter
    _scan_counter += 1
    return f"scan_{_scan_counter}"


# ────────────────── 工具函数 ──────────────────

def compute_partial_hash(filepath, chunk_size=65536):
    """计算文件前 1MB 的 SHA-256 作为快速指纹，用于两阶段哈希的第一阶段筛选。
    不同文件的前 1MB 几乎不可能相同，可大幅减少需要全量哈希的文件数。
    失败返回 None"""
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            remaining = 1048576  # 1 MB
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                chunk = f.read(read_size)
                if not chunk:
                    break
                sha256.update(chunk)
                remaining -= len(chunk)
        return sha256.hexdigest()
    except (OSError, PermissionError):
        return None


def compute_file_hash(filepath, chunk_size=65536):
    """计算文件完整 SHA-256，返回十六进制字符串；失败返回 None"""
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    except (OSError, PermissionError):
        return None


def format_size(size_bytes):
    """将字节数格式化为易读字符串"""
    if size_bytes == 0:
        return "0 B"
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def collect_files(folder, recursive, skip_empty):
    """收集文件夹中所有文件，返回 [(filepath, size), ...]"""
    files = []
    if recursive:
        for dirpath, _dirs, filenames in os.walk(folder):
            for fname in filenames:
                fp = os.path.join(dirpath, fname)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                if skip_empty and sz == 0:
                    continue
                files.append((fp, sz))
    else:
        try:
            for fname in os.listdir(folder):
                fp = os.path.join(folder, fname)
                if os.path.isfile(fp):
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        continue
                    if skip_empty and sz == 0:
                        continue
                    files.append((fp, sz))
        except OSError:
            pass
    return files


# ────────────────── 认证路由 ──────────────────

_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - 重复文件检测清理工具</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                         "Microsoft YaHei", sans-serif;
            background: #f5f6fa; display: flex; justify-content: center; align-items: center;
            min-height: 100vh;
        }
        .login-card {
            background: #fff; border-radius: 12px; padding: 40px;
            box-shadow: 0 4px 24px rgba(0,0,0,.1); width: 380px; text-align: center;
        }
        .login-card h2 { font-size: 20px; color: #2c3e50; margin-bottom: 8px; }
        .login-card p { font-size: 13px; color: #7f8c8d; margin-bottom: 24px; }
        .login-card input {
            width: 100%; padding: 10px 14px; border: 1px solid #e0e4ea; border-radius: 6px;
            font-size: 14px; outline: none; margin-bottom: 16px; transition: border-color .2s;
        }
        .login-card input:focus { border-color: #3498db; }
        .login-card button {
            width: 100%; padding: 10px; background: #3498db; color: #fff; border: none;
            border-radius: 6px; font-size: 14px; cursor: pointer; transition: background .2s;
        }
        .login-card button:hover { background: #2980b9; }
        .error-msg { color: #e74c3c; font-size: 13px; margin-bottom: 12px; display: none; }
    </style>
</head>
<body>
    <div class="login-card">
        <h2>重复文件检测清理工具</h2>
        <p>请输入访问密码</p>
        <div class="error-msg" id="error-msg">密码错误，请重试</div>
        <form method="POST" action="/login">
            <input type="password" name="password" id="pwd-input" placeholder="密码" autofocus>
            <button type="submit">登 录</button>
        </form>
    </div>
    <script>
        if (new URLSearchParams(location.search).has('error')) {
            document.getElementById('error-msg').style.display = 'block';
        }
        document.getElementById('pwd-input').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') this.form.submit();
        });
    </script>
</body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    """登录页面：验证密码并设置会话 Cookie"""
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == _config.get('password', '') and pwd != '':
            resp = make_response(redirect('/'))
            resp.set_cookie(AUTH_COOKIE, _session_token, httponly=True, samesite='Lax')
            return resp
        return redirect('/login?error=1')

    # 无需密码时直接设置 Cookie 并跳转首页
    if not _config.get('password'):
        resp = make_response(redirect('/'))
        resp.set_cookie(AUTH_COOKIE, _session_token, httponly=True, samesite='Lax')
        return resp

    return _LOGIN_HTML


@app.route("/logout")
def logout():
    """登出：清除会话 Cookie"""
    resp = make_response(redirect('/login'))
    resp.delete_cookie(AUTH_COOKIE)
    return resp


# ────────────────── 路由 ──────────────────

@app.route("/")
def index():
    # 无需密码时跳过认证，但仍需设置 Cookie 以便 API 调用
    if not _config.get('password'):
        resp = make_response(render_template("index.html", version=__version__))
        resp.set_cookie(AUTH_COOKIE, _session_token, httponly=True, samesite='Lax')
        return resp
    token = request.cookies.get(AUTH_COOKIE)
    if not secrets.compare_digest(token or '', _session_token):
        return redirect('/login')
    return render_template("index.html", version=__version__)


@app.route("/api/scan", methods=["POST"])
@require_auth
def api_scan():
    """启动扫描，返回 scan_id，通过 SSE 推送进度"""
    data = request.get_json(force=True)
    folder = data.get("folder", "").strip()
    recursive = data.get("recursive", True)
    skip_empty = data.get("skip_empty", True)
    keep_rule = data.get("keep_rule", "shortest")  # shortest | longest | manual

    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "无效的文件夹路径"}), 400

    scan_id = _new_scan_id()
    event_queue = queue.Queue()

    with _session_lock:
        _sessions[scan_id] = {
            "folder": folder,
            "status": "running",
            "events": event_queue,
            "results": None,
            "all_files": [],        # [(fp, size), ...]
            "duplicate_groups": [], # [[fp, ...], ...]
            "keep_files": set(),
            "dup_file_set": set(),
            "keep_rule": keep_rule,
            "cancel_requested": False,
            "paused": False,
        }

    # 在后台线程执行扫描
    t = threading.Thread(target=_run_scan, args=(scan_id, folder, recursive, skip_empty, keep_rule))
    t.daemon = True
    t.start()

    return jsonify({"scan_id": scan_id})


def _run_scan(scan_id, folder, recursive, skip_empty, keep_rule="shortest"):
    """后台扫描线程"""

    def _wait_if_paused():
        """暂停时阻塞，恢复后返回。取消时返回 True"""
        notified = False
        while True:
            with _session_lock:
                session = _sessions.get(scan_id)
                if not session or session.get("cancel_requested"):
                    return True
                if not session.get("paused"):
                    break
            if not notified:
                q.put(json.dumps({"type": "paused", "message": "扫描已暂停"}))
                notified = True
            time.sleep(0.3)
        if notified:
            q.put(json.dumps({"type": "resumed", "message": "扫描继续…"}))
        return False

    with _session_lock:
        session = _sessions.get(scan_id)
    if not session:
        return
    q = session["events"]

    try:
        # 阶段 1：收集文件
        q.put(json.dumps({"type": "phase", "phase": "collect", "message": "正在收集文件列表…"}))
        raw_files = []
        if recursive:
            for dirpath, _dirs, filenames in os.walk(folder):
                # 检查是否已取消或暂停
                if _wait_if_paused():
                    q.put(json.dumps({"type": "cancelled", "message": "扫描已停止"}))
                    with _session_lock:
                        if scan_id in _sessions:
                            _sessions[scan_id]["status"] = "cancelled"
                    return
                for fname in filenames:
                    raw_files.append(os.path.join(dirpath, fname))
        else:
            try:
                for fname in os.listdir(folder):
                    fp = os.path.join(folder, fname)
                    if os.path.isfile(fp):
                        raw_files.append(fp)
            except OSError as e:
                logger.warning("列出目录失败 %s: %s", folder, e)

        # 构建 all_files
        all_files = []
        for fp in raw_files:
            try:
                sz = os.path.getsize(fp)
            except OSError as e:
                logger.debug("获取文件大小失败 %s: %s", fp, e)
                continue
            if skip_empty and sz == 0:
                continue
            all_files.append((fp, sz))

        with _session_lock:
            if scan_id in _sessions:
                _sessions[scan_id]["all_files"] = all_files

        q.put(json.dumps({
            "type": "phase",
            "phase": "collect_done",
            "message": f"已列出 {len(all_files)} 个文件",
            "file_count": len(all_files),
        }))

        # 阶段 2：按大小分组
        q.put(json.dumps({"type": "phase", "phase": "hash", "message": "正在计算文件哈希…"}))
        size_groups = defaultdict(list)
        for fp, sz in all_files:
            size_groups[sz].append(fp)

        candidates = {sz: paths for sz, paths in size_groups.items() if len(paths) > 1}
        total_candidates = sum(len(p) for p in candidates.values())
        total_bytes = sum(sz * len(paths) for sz, paths in candidates.items())

        if total_candidates == 0:
            q.put(json.dumps({
                "type": "done",
                "duplicate_groups": [],
                "total_groups": 0,
                "duplicate_count": 0,
                "space_saved": "0 B",
                "message": "未发现重复文件",
            }))
            with _session_lock:
                if scan_id in _sessions:
                    _sessions[scan_id]["status"] = "done"
            return

        # 阶段 3：两阶段哈希（先 partial hash 快速筛选，再全量哈希确认）
        n_workers = max(2, os.cpu_count() or 2)
        hash_errors = 0

        # ── 阶段 3a：并行计算 partial hash，快速排除唯一文件 ──
        q.put(json.dumps({
            "type": "phase",
            "phase": "partial_hash",
            "message": f"正在快速筛选文件指纹（{n_workers} 线程并行）…",
            "file_count": total_candidates,
        }))

        partial_groups = defaultdict(list)   # partial_hash -> [(fp, sz), ...]
        partial_done = 0
        partial_lock = threading.Lock()

        def _worker_partial(item):
            fp, sz = item
            with _session_lock:
                session = _sessions.get(scan_id)
                if session and session.get("cancel_requested"):
                    return None
            h = compute_partial_hash(fp)
            with partial_lock:
                nonlocal partial_done
                partial_done += 1
                pct = int(partial_done / total_candidates * 100)
                q.put(json.dumps({
                    "type": "progress",
                    "progress": pct,
                    "current": f"{partial_done}/{total_candidates}",
                    "total": f"{total_candidates} 个候选文件",
                    "current_files": partial_done,
                    "total_files": total_candidates,
                }))
            return (fp, sz, h)

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            all_items = [(fp, sz) for sz, paths in candidates.items() for fp in paths]
            futures = {pool.submit(_worker_partial, item): item for item in all_items}
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue  # cancelled
                fp, sz, h = result
                if h:
                    partial_groups[h].append((fp, sz))
                else:
                    with partial_lock:
                        hash_errors += 1
                    logger.debug("Partial hash 失败: %s", fp)

        # 检查取消
        with _session_lock:
            session = _sessions.get(scan_id)
            if session and session.get("cancel_requested"):
                q.put(json.dumps({"type": "cancelled", "message": "扫描已停止"}))
                session["status"] = "cancelled"
                return

        # 仅保留 partial hash 相同的文件组（>=2 个文件），其余直接排除
        need_full_hash = {h: items for h, items in partial_groups.items() if len(items) > 1}
        full_hash_candidates = sum(len(v) for v in need_full_hash.values())
        skipped = total_candidates - full_hash_candidates

        if skipped > 0:
            logger.info("Partial hash 筛选：跳过 %d 个唯一文件，剩余 %d 个需全量哈希", skipped, full_hash_candidates)

        if full_hash_candidates == 0:
            q.put(json.dumps({
                "type": "done",
                "duplicate_groups": [],
                "total_groups": 0,
                "duplicate_count": 0,
                "space_saved": "0 B",
                "message": "未发现重复文件（所有文件大小或内容均唯一）",
            }))
            with _session_lock:
                if scan_id in _sessions:
                    _sessions[scan_id]["status"] = "done"
            return

        # ── 阶段 3b：对筛选后的文件并行计算全量 SHA-256 ──
        q.put(json.dumps({
            "type": "phase",
            "phase": "full_hash",
            "message": f"正在计算文件哈希（{full_hash_candidates} 个文件，{n_workers} 线程并行）…",
            "file_count": full_hash_candidates,
        }))

        hash_groups = defaultdict(list)
        full_done = 0
        full_done_bytes = 0
        full_lock = threading.Lock()

        def _worker_full(item):
            fp, sz = item
            with _session_lock:
                session = _sessions.get(scan_id)
                if session and session.get("cancel_requested"):
                    return None
            h = compute_file_hash(fp)
            with full_lock:
                nonlocal full_done, full_done_bytes
                full_done += 1
                full_done_bytes += sz
                pct = int(full_done_bytes / total_bytes * 100) if total_bytes > 0 else 100
                q.put(json.dumps({
                    "type": "progress",
                    "progress": pct,
                    "current": format_size(full_done_bytes),
                    "total": format_size(total_bytes),
                    "current_files": full_done,
                    "total_files": full_hash_candidates,
                }))
            return (fp, h)

        full_items = [(fp, sz) for items in need_full_hash.values() for fp, sz in items]
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_worker_full, item): item for item in full_items}
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue
                fp, h = result
                if h:
                    hash_groups[h].append(fp)
                else:
                    with full_lock:
                        hash_errors += 1
                    logger.debug("全量哈希失败: %s", fp)

        if hash_errors > 0:
            logger.warning("扫描 %s: %d 个文件哈希计算失败（已跳过）", folder, hash_errors)

        # 筛选真正的重复组
        duplicate_groups = [paths for paths in hash_groups.values() if len(paths) > 1]
        dup_file_set = set()
        keep_files = set()
        total_to_delete = 0
        total_space = 0

        for group in duplicate_groups:
            if keep_rule == "longest":
                group_sorted = sorted(
                    group,
                    key=lambda p: (-len(os.path.basename(p)), os.path.basename(p)),
                )
                keep_file = group_sorted[0]
            elif keep_rule == "manual":
                group_sorted = sorted(
                    group,
                    key=lambda p: (len(os.path.basename(p)), os.path.basename(p)),
                )
                keep_file = None
            else:  # shortest
                group_sorted = sorted(
                    group,
                    key=lambda p: (len(os.path.basename(p)), os.path.basename(p)),
                )
                keep_file = group_sorted[0]

            if keep_file:
                keep_files.add(keep_file)
            for fp in group_sorted:
                dup_file_set.add(fp)
                if keep_file and fp != keep_file:
                    total_to_delete += 1
                    try:
                        total_space += os.path.getsize(fp)
                    except OSError:
                        pass

        with _session_lock:
            if scan_id in _sessions:
                _sessions[scan_id]["duplicate_groups"] = duplicate_groups
                _sessions[scan_id]["keep_files"] = keep_files
                _sessions[scan_id]["dup_file_set"] = dup_file_set
                _sessions[scan_id]["status"] = "done"

        q.put(json.dumps({
            "type": "done",
            "duplicate_groups": duplicate_groups,
            "total_groups": len(duplicate_groups),
            "duplicate_count": total_to_delete,
            "space_saved": format_size(total_space),
            "message": f"扫描完成：{len(duplicate_groups)} 组重复，{total_to_delete} 个待删除",
        }))
        logger.info("扫描完成 %s: %d 组重复, %d 个待删除", folder, len(duplicate_groups), total_to_delete)

    except Exception as e:
        logger.error("扫描线程异常 scan_id=%s: %s\n%s", scan_id, e, traceback.format_exc())
        # 推送错误事件给前端
        q.put(json.dumps({
            "type": "error",
            "message": f"扫描出错: {e}",
        }))
        with _session_lock:
            if scan_id in _sessions:
                _sessions[scan_id]["status"] = "error"


@app.route("/api/scan/<scan_id>/progress")
@require_auth
def api_scan_progress(scan_id):
    """SSE 端点，推送扫描进度"""
    with _session_lock:
        session = _sessions.get(scan_id)
    if not session:
        return jsonify({"error": "无效的 scan_id"}), 404

    q = session["events"]

    def generate():
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {msg}\n\n"
                if '"type": "done"' in msg or '"type": "cancelled"' in msg:
                    break
            except queue.Empty:
                # 超时发送心跳
                yield "data: {\"type\": \"ping\"}\n\n"
                # 检查是否已完成或已取消
                with _session_lock:
                    s = _sessions.get(scan_id)
                    if s and s["status"] in ("done", "cancelled", "error"):
                        break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/api/scan/<scan_id>/stop", methods=["POST"])
@require_auth
def api_scan_stop(scan_id):
    """停止正在进行的扫描"""
    with _session_lock:
        session = _sessions.get(scan_id)
        if not session:
            return jsonify({"error": "无效的 scan_id"}), 404
        if session["status"] != "running":
            return jsonify({"error": "扫描已结束，无法停止"}), 400
        session["cancel_requested"] = True
    logger.info("用户请求停止扫描 scan_id=%s", scan_id)
    return jsonify({"ok": True})


@app.route("/api/scan/<scan_id>/pause", methods=["POST"])
@require_auth
def api_scan_pause(scan_id):
    """暂停/继续扫描（toggle）"""
    with _session_lock:
        session = _sessions.get(scan_id)
        if not session:
            return jsonify({"error": "无效的 scan_id"}), 404
        if session["status"] != "running":
            return jsonify({"error": "扫描已结束，无法暂停"}), 400
        session["paused"] = not session["paused"]
        is_paused = session["paused"]
    action = "暂停" if is_paused else "继续"
    logger.info("用户%s扫描 scan_id=%s", action, scan_id)
    return jsonify({"ok": True, "paused": is_paused})


@app.route("/api/scan/latest")
@require_auth
def api_scan_latest():
    """返回最近一次扫描的信息（任意状态），用于页面恢复"""
    with _session_lock:
        if _scan_counter <= 0:
            return jsonify({"scan_id": None})
        latest_id = f"scan_{_scan_counter}"
        session = _sessions.get(latest_id)
        if not session:
            return jsonify({"scan_id": None})
        return jsonify({
            "scan_id": latest_id,
            "folder": session["folder"],
            "status": session["status"],
            "paused": session.get("paused", False),
        })
    return jsonify({"scan_id": None})


@app.route("/api/scan/<scan_id>/details")
@require_auth
def api_scan_details(scan_id):
    """获取扫描详细结果（用于填充前端列表）"""
    with _session_lock:
        session = _sessions.get(scan_id)
    if not session:
        return jsonify({"error": "无效的 scan_id"}), 404

    folder = session["folder"]
    all_files = session["all_files"]
    duplicate_groups = session["duplicate_groups"]
    keep_files = session["keep_files"]
    dup_file_set = session["dup_file_set"]
    keep_rule = session.get("keep_rule", "shortest")

    # 构建所有文件列表
    all_files_data = []
    for fp, sz in all_files:
        fname = os.path.basename(fp)
        try:
            rel = os.path.relpath(fp, folder)
        except ValueError:
            rel = fp
        status = "keep" if fp in keep_files else ("dup" if fp in dup_file_set else "normal")
        all_files_data.append({
            "path": fp,
            "name": fname,
            "size": sz,
            "size_str": format_size(sz),
            "rel": rel,
            "status": status,
        })

    # 按保留规则排序（保留文件在前）
    groups_data = []
    for idx, group in enumerate(duplicate_groups, 1):
        if keep_rule == "longest":
            group_sorted = sorted(
                group,
                key=lambda p: (-len(os.path.basename(p)), os.path.basename(p)),
            )
            keep_file = group_sorted[0]
        elif keep_rule == "manual":
            group_sorted = sorted(
                group,
                key=lambda p: (len(os.path.basename(p)), os.path.basename(p)),
            )
            keep_file = None
        else:  # shortest
            group_sorted = sorted(
                group,
                key=lambda p: (len(os.path.basename(p)), os.path.basename(p)),
            )
            keep_file = group_sorted[0]
        try:
            file_size = os.path.getsize(keep_file) if keep_file else (
                os.path.getsize(group_sorted[0]) if group_sorted else 0
            )
        except OSError:
            file_size = 0
        # 手动模式下没有自动可释放空间统计
        if keep_file:
            space_saved = file_size * (len(group_sorted) - 1)
        else:
            space_saved = 0

        files_in_group = []
        for fp in group_sorted:
            fname = os.path.basename(fp)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                sz = 0
            try:
                rel = os.path.relpath(fp, folder)
            except ValueError:
                rel = fp
            is_keep = fp == keep_file
            files_in_group.append({
                "path": fp,
                "name": fname,
                "size": sz,
                "size_str": format_size(sz),
                "rel": rel,
                "is_keep": is_keep,
            })

        groups_data.append({
            "index": idx,
            "count": len(group_sorted),
            "file_size": file_size,
            "file_size_str": format_size(file_size),
            "space_saved": space_saved,
            "space_saved_str": format_size(space_saved),
            "files": files_in_group,
        })

    return jsonify({
        "folder": folder,
        "all_files": all_files_data,
        "duplicate_groups": groups_data,
        "total_groups": len(duplicate_groups),
        "total_files": len(all_files_data),
        "keep_rule": keep_rule,
    })


@app.route("/api/delete", methods=["POST"])
@require_auth
def api_delete():
    """删除选中的文件"""
    data = request.get_json(force=True)
    files = data.get("files", [])

    if not files:
        return jsonify({"error": "没有指定要删除的文件"}), 400

    deleted = 0
    errors = []
    total_size = 0

    for fp in files:
        try:
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                os.remove(fp)
                deleted += 1
                total_size += sz
            else:
                errors.append(f"{os.path.basename(fp)}：文件不存在")
        except OSError as e:
            logger.error("删除文件失败 %s: %s", fp, e)
            errors.append(f"{os.path.basename(fp)}：{str(e)}")

    return jsonify({
        "deleted": deleted,
        "errors": errors,
        "total_size": total_size,
        "total_size_str": format_size(total_size),
    })


@app.route("/api/open", methods=["POST"])
@require_auth
def api_open():
    """用系统默认程序打开文件"""
    data = request.get_json(force=True)
    fp = data.get("path", "")
    if not fp or not os.path.exists(fp):
        return jsonify({"error": "文件不存在"}), 404
    try:
        if sys.platform.startswith("win"):
            os.startfile(fp)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", fp])
        else:
            subprocess.Popen(["xdg-open", fp])
        return jsonify({"ok": True})
    except OSError as e:
        logger.error("打开文件失败 %s: %s", fp, e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/open-folder", methods=["POST"])
@require_auth
def api_open_folder():
    """打开文件所在目录"""
    data = request.get_json(force=True)
    fp = data.get("path", "")
    if not fp:
        return jsonify({"error": "未指定路径"}), 400

    # 如果传的是文件路径，取其所在目录；如果传的就是目录，直接用
    if os.path.isfile(fp):
        target = os.path.dirname(fp)
    elif os.path.isdir(fp):
        target = fp
    else:
        # 路径不存在，尝试打开父目录
        target = os.path.dirname(fp) or os.getcwd()

    if not os.path.isdir(target):
        return jsonify({"error": "目录不存在"}), 404

    try:
        if sys.platform.startswith("win"):
            # explorer /select, 会高亮选中该文件（如果 fp 是文件）
            if os.path.isfile(fp):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(fp)])
            else:
                os.startfile(target)
        elif sys.platform == "darwin":
            if os.path.isfile(fp):
                subprocess.Popen(["open", "-R", fp])
            else:
                subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return jsonify({"ok": True})
    except OSError as e:
        logger.error("打开目录失败 %s: %s", fp, e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/browse", methods=["POST"])
@require_auth
def api_browse():
    """返回指定目录的子目录列表（跨平台自适应）"""
    data = request.get_json(force=True)
    path = data.get("path", "").strip()
    logger.debug("[api/browse] 请求路径: %r", path)

    # Windows: 如果路径为空或 /，返回所有盘符
    if (not path or path == "/") and sys.platform.startswith("win"):
        drives = []
        for d in range(ord("A"), ord("Z") + 1):
            drive = chr(d) + ":\\"
            if os.path.exists(drive):
                drives.append({"name": drive, "path": drive})
        logger.debug("[api/browse] Windows 盘符列表: %d 个", len(drives))
        return jsonify({"path": "", "entries": drives, "is_drives": True})

    # Linux/macOS 根目录
    if not path or path == "/":
        path = "/"

    try:
        if not os.path.isdir(path):
            logger.warning("[api/browse] 路径不是有效目录: %r，回退到默认目录", path)
            # Windows: 如果路径不存在，回退到用户目录
            if sys.platform.startswith("win"):
                path = os.path.expanduser("~")
            else:
                path = "/"
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full) and not name.startswith("."):
                entries.append({"name": name, "path": full})
        logger.debug("[api/browse] 目录 %r 包含 %d 个子目录", path, len(entries))
        return jsonify({"path": path, "entries": entries})
    except PermissionError as e:
        logger.error("[api/browse] 权限不足: %r - %s", path, e)
        home = os.path.expanduser("~")
        return jsonify({"path": home, "entries": [], "error": f"无权访问该目录: {path}"}), 403
    except OSError as e:
        logger.error("[api/browse] 读取目录失败: %r - %s", path, e)
        home = os.path.expanduser("~")
        return jsonify({"path": home, "entries": [], "error": f"读取目录失败: {str(e)}"}), 500


# ────────────────── 入口 ──────────────────

def _open_browser(port=None):
    """延迟 1.5 秒后自动打开浏览器"""
    port = port or DEFAULT_PORT
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}")


if __name__ == "__main__":
    # 优先级：环境变量 > 命令行参数/配置文件 > 默认值
    host = _config.get('host', '127.0.0.1')
    port = _config.get('port', DEFAULT_PORT)
    password = _config.get('password', '')

    # 环境变量覆盖（Docker 部署首选）
    env_host = os.environ.get("DUPFINDER_HOST")
    if env_host:
        host = env_host.strip()
    env_port = os.environ.get("DUPFINDER_PORT")
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            pass
    env_password = os.environ.get("DUPFINDER_PASSWORD")
    if env_password is not None:
        password = env_password.strip()
        _config['password'] = password

    auth_status = "已启用" if password else "未设置密码（无认证）"
    print("=" * 60)
    print(f"  重复文件检测清理工具 Web 版 v{__version__}")
    print(f"  访问: http://{host}:{port}")
    print(f"  密码认证: {auth_status}")
    if getattr(sys, 'frozen', False):
        import platform
        env_label = "Linux" if platform.system() == "Linux" else "Windows"
        print(f"  运行环境: {env_label} EXE (单文件模式)")
    print("=" * 60)

    # EXE 模式下自动打开浏览器
    if getattr(sys, 'frozen', False):
        t = threading.Thread(target=_open_browser, args=(port,), daemon=True)
        t.start()

    app.run(host=host, port=port, debug=False, threaded=True)
