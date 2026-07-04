#!/usr/bin/env python3
"""
重复文件检测清理工具 - GUI 启动器
提供无命令行窗口的 tkinter GUI 界面：
  - 顶部：启动运行 / 停止运行 按钮 + 端口配置 + 状态显示
  - 底部：运行日志（终端风格深色背景）
"""

import os
import sys
import threading
import logging
import webbrowser
import time
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import ttk, scrolledtext

# ────────────────── PyInstaller 资源路径 ──────────────────
def _resource_path(relative):
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative)

_TEMPLATE_DIR = _resource_path('templates')
_STATIC_DIR = _resource_path('static')

# 导入 Flask app — 需要在设置好路径后
from werkzeug.serving import make_server
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

# 重新创建 Flask app（确保 template/static 路径正确）
# 直接从 app 模块导入所有路由和逻辑
import importlib.util

# 动态导入 app.py（避免触发 if __name__ == "__main__"）
_spec = importlib.util.spec_from_file_location(
    "dupfinder_app",
    _resource_path("app.py")
)
_mod = importlib.util.module_from_spec(_spec)
# 注入正确的 Flask 实例
_mod.__dict__["__file__"] = _resource_path("app.py")
_spec.loader.exec_module(_mod)
app = _mod.app

# 从 app 模块读取已加载的配置和版本号
_cfg = _mod._config
_version = _mod.__version__
HOST = _cfg.get('host', '127.0.0.1')
DEFAULT_PORT = _cfg.get('port', 36901)


# ────────────────── 日志处理器 ──────────────────

class GUILogHandler(logging.Handler):
    """将 logging 输出重定向到 tkinter Text 控件"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        msg = self.format(record)
        self.callback(msg)


# ────────────────── 可控的 Flask 服务器 ──────────────────

class ServerThread(threading.Thread):
    """在子线程中运行 Flask，支持优雅关闭"""

    def __init__(self, flask_app, host, port, error_callback=None):
        super().__init__(daemon=True)
        self.flask_app = flask_app
        self.host = host
        self.port = port
        self.error_callback = error_callback
        self.server = make_server(host, port, flask_app, threaded=True)
        self.ctx = flask_app.app_context()
        self.ctx.push()

    def run(self):
        try:
            self.server.serve_forever()
        except Exception as e:
            logging.getLogger("dupfinder").error(
                "Flask 服务异常: %s\n%s", e, traceback.format_exc()
            )
            if self.error_callback:
                self.error_callback(f"服务运行异常: {e}")

    def shutdown(self):
        self.server.shutdown()


# ────────────────── GUI 主窗口 ──────────────────

class DupFinderGUI:

    def __init__(self):
        self.server_thread = None
        self.is_running = False
        self.current_port = DEFAULT_PORT

        self.root = tk.Tk()
        self.root.title(f"重复文件检测清理工具 v{_version}")
        self.root.geometry("900x520")
        self.root.minsize(600, 400)
        self.root.configure(bg="#f0f0f0")

        # 设置窗口图标
        _icon_path = _resource_path("app.ico")
        if os.path.isfile(_icon_path):
            try:
                self.root.iconbitmap(_icon_path)
            except Exception:
                pass

        # 窗口居中
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")

        self._build_ui()
        self._setup_logging()

        # 关闭窗口时停止服务
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────── UI 构建 ───────────────

    def _build_ui(self):
        style = ttk.Style()
        style.configure("Start.TButton", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Stop.TButton", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Open.TButton", font=("Microsoft YaHei UI", 10))
        style.configure("Clear.TButton", font=("Microsoft YaHei UI", 9))

        # ── 顶部工具栏 ──
        top_frame = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        top_frame.pack(fill=tk.X)

        self.btn_start = ttk.Button(
            top_frame, text="▶  启动运行", style="Start.TButton",
            command=self.start_server, width=14
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = ttk.Button(
            top_frame, text="■  停止运行", style="Stop.TButton",
            command=self.stop_server, width=14, state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT, padx=8)

        # 端口配置
        ttk.Label(top_frame, text="端口：",
                  font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(4, 2))
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.port_spin = ttk.Spinbox(
            top_frame, from_=1024, to=65535, width=7,
            textvariable=self.port_var, font=("Consolas", 11)
        )
        self.port_spin.pack(side=tk.LEFT, padx=(0, 4))

        # 分隔
        ttk.Separator(top_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=12
        )

        self.status_var = tk.StringVar(value="● 已停止")
        self.lbl_status = ttk.Label(
            top_frame, textvariable=self.status_var,
            font=("Microsoft YaHei UI", 10), foreground="#999999"
        )
        self.lbl_status.pack(side=tk.LEFT, padx=(0, 16))

        self.lbl_url = ttk.Label(
            top_frame, text="", font=("Microsoft YaHei UI", 9),
            foreground="#0066cc", cursor="hand2"
        )
        self.lbl_url.pack(side=tk.LEFT)
        self.lbl_url.bind("<Button-1>", lambda e: self.open_browser())

        # 右侧按钮
        right_frame = ttk.Frame(top_frame)
        right_frame.pack(side=tk.RIGHT)

        self.btn_clear = ttk.Button(
            right_frame, text="清空日志", style="Clear.TButton",
            command=self.clear_log
        )
        self.btn_clear.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_open = ttk.Button(
            right_frame, text="🌐 打开浏览器", style="Open.TButton",
            command=self.open_browser, state=tk.DISABLED
        )
        self.btn_open.pack(side=tk.LEFT)

        # ── 底部日志区 ──
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        log_frame = ttk.Frame(self.root, padding=(12, 6, 12, 12))
        log_frame.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(log_frame)
        header.pack(fill=tk.X)
        ttk.Label(
            header, text="📋 运行日志",
            font=("Microsoft YaHei UI", 10, "bold")
        ).pack(side=tk.LEFT)

        # 终端风格深色文本区
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=18,
            font=("Consolas", 10),
            bg="#1e1e1e",
            fg="#cccccc",
            insertbackground="#cccccc",
            selectbackground="#264f78",
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # 配置标签样式（不同日志级别不同颜色）
        self.log_text.tag_configure("INFO", foreground="#4ec9b0")
        self.log_text.tag_configure("WARNING", foreground="#dcdcaa")
        self.log_text.tag_configure("ERROR", foreground="#f44747")
        self.log_text.tag_configure("HTTP", foreground="#569cd6")
        self.log_text.tag_configure("SYSTEM", foreground="#c586c0")
        self.log_text.tag_configure("NORMAL", foreground="#cccccc")

    # ─────────────── 日志 ───────────────

    def _setup_logging(self):
        """配置 logging，将 werkzeug 和 Flask 的日志重定向到 GUI"""
        self.log_handler = GUILogHandler(self._log)
        self.log_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(message)s")
        self.log_handler.setFormatter(formatter)

        # werkzeug 日志（HTTP 请求）
        werkzeug_logger = logging.getLogger("werkzeug")
        werkzeug_logger.setLevel(logging.INFO)
        werkzeug_logger.addHandler(self.log_handler)

        # Flask 根日志
        flask_logger = logging.getLogger("flask")
        flask_logger.setLevel(logging.INFO)
        flask_logger.addHandler(self.log_handler)

        # 确保不输出到控制台
        for lg in [werkzeug_logger, flask_logger]:
            lg.propagate = False

    def _log(self, message, level="NORMAL"):
        """线程安全地向日志区追加文本"""
        def _append():
            self.log_text.config(state=tk.NORMAL)
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{ts}] ", "SYSTEM")
            self.log_text.insert(tk.END, message + "\n", level)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        # 如果是从非主线程调用，用 after 调度
        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            self.root.after(0, _append)

    def _log_system(self, message, level="SYSTEM"):
        self._log(message, level)

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ─────────────── 服务器控制 ───────────────

    def start_server(self):
        if self.is_running:
            return

        # 读取端口
        try:
            port = int(self.port_var.get())
            if port < 1024 or port > 65535:
                raise ValueError
        except (ValueError, TypeError):
            self._log("端口无效，请输入 1024-65535 范围内的数字", "ERROR")
            return

        self._log_system("=" * 50)
        self._log_system("正在启动 Flask 服务...", "SYSTEM")

        try:
            self.server_thread = ServerThread(
                app, HOST, port, error_callback=lambda msg: self._log(msg, "ERROR")
            )
            self.server_thread.start()
            self.is_running = True
            self.current_port = port
        except OSError as e:
            self._log(f"启动失败: {e}", "ERROR")
            logging.getLogger("dupfinder").error("启动服务失败: %s", e)
            return

        # 更新 UI 状态
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_open.config(state=tk.NORMAL)
        self.port_spin.config(state=tk.DISABLED)
        self.status_var.set("● 运行中")
        self.lbl_status.config(foreground="#27ae60")
        self.lbl_url.config(text=f"http://localhost:{port}")

        self._log_system(f"服务已启动，监听 {HOST}:{port}", "SYSTEM")
        self._log_system(f"浏览器访问: http://localhost:{port}", "INFO")
        if _cfg.get('password'):
            self._log_system("密码认证: 已启用", "INFO")
        else:
            self._log_system("密码认证: 未设置密码（无认证）", "WARNING")
        self._log_system("=" * 50, "SYSTEM")

        # 延迟自动打开浏览器
        threading.Thread(
            target=lambda: (time.sleep(1.2), self.open_browser()),
            daemon=True
        ).start()

    def stop_server(self):
        if not self.is_running:
            return

        self._log_system("正在停止服务...", "SYSTEM")

        try:
            self.server_thread.shutdown()
            self.server_thread.join(timeout=5)
        except Exception as e:
            self._log(f"停止服务时出错: {e}", "ERROR")
            logging.getLogger("dupfinder").error("停止服务异常: %s", e)

        self.is_running = False

        # 更新 UI 状态
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_open.config(state=tk.DISABLED)
        self.port_spin.config(state=tk.NORMAL)
        self.status_var.set("● 已停止")
        self.lbl_status.config(foreground="#999999")
        self.lbl_url.config(text="")

        self._log_system("服务已停止", "SYSTEM")

    def open_browser(self):
        port = getattr(self, 'current_port', DEFAULT_PORT)
        webbrowser.open(f"http://localhost:{port}")

    # ─────────────── 退出 ───────────────

    def _on_close(self):
        if self.is_running:
            self.stop_server()
        self.root.destroy()

    def run(self):
        self._log_system(f"重复文件检测清理工具 v{_version} 已就绪", "SYSTEM")
        self._log_system("点击「启动运行」开始使用", "INFO")
        self._log_system("")
        self.root.mainloop()


# ────────────────── 入口 ──────────────────

if __name__ == "__main__":
    # 冻结模式下修复 stdout/stderr（console=False 时为 None）
    if getattr(sys, 'frozen', False):
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')

    gui = DupFinderGUI()
    gui.run()
