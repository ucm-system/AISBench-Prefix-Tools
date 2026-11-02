#!/usr/bin/env python3
"""
AISBenchPrefixTools - Windows GUI应用程序
用于远程部署和配置AISBench测试环境

功能流程:
  1. 连接远程执行机 (SSH)
  2. 选择执行机已有镜像或上传镜像tar包, 配置模型并部署容器
  3. 配置config.py (直接写入容器内部)
  4. 设计测试用例
  5. 执行测试并收集结果 (测试代码/日志均在容器内, 宿主机临时目录部署后自动删除)
"""

import os
import re
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from typing import Optional, Callable, Tuple

from ssh_manager import SSHManager
from docker_manager import DockerManager, describe_test_state
from config_manager import ConfigManager
from test_designer import TestDesigner
from log_parser import parse_log_directory
from log_tools import RemoteLogBrowser, KV_GREP_COMMAND
from result_compare import ResultCompareDialog
from i18n import (
    LocalizedButton,
    LocalizedCheckbutton,
    LocalizedLabel,
    LocalizedRadiobutton,
    LocalizedTtkButton,
    SUPPORTED_LANGUAGES,
    askyesno,
    askyesnocancel,
    get_language,
    set_language,
    showerror,
    showinfo,
    showwarning,
    tr,
    trf,
)
from settings_manager import load_settings, save_settings


# ============================================================
#  样式常量
# ============================================================
COLOR_PRIMARY = "#2563eb"
COLOR_BG = "#f8fafc"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#e2e8f0"
COLOR_TEXT = "#1e293b"
COLOR_TEXT_MUTED = "#64748b"
COLOR_SUCCESS = "#16a34a"
COLOR_ERROR = "#dc2626"
COLOR_WARNING = "#d97706"


class LiveLogHandler:
    """
    实时日志处理器:
    - 按终端语义处理 \\r (进度条单行覆盖刷新), 清理 ANSI 转义码
    - 折叠 \\n 结尾的重复状态行 (ais-bench POST=... / tqdm 进度条),
      请求发送阶段的周期性状态行只保留最新一行, 不刷屏
    - 完整行直接落地; 未完成行(pending)实时覆盖显示, finalize 时落地
    """
    ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
    STATUS_RE = re.compile(
        r'^\s*(?:'
        r'POST=\d+'
        r'|Progress:.*\d+%'
        r'|Calculating performance details:.*\d+%'
        r'|\d{1,3}%\s*\|'
        r')'
    )

    def __init__(self, widget):
        self.widget = widget
        self.raw = ""
        self.has_pending = False
        self._pending_held = False
        self._lock = threading.Lock()

    def append(self, text: str):
        with self._lock:
            self.raw += text

    def reset(self):
        with self._lock:
            self.raw = ""
            self.has_pending = False
            self._pending_held = False

    def _clean(self, s: str) -> str:
        s = self.ANSI_RE.sub('', s)
        if s.endswith('\r'):
            s = s[:-1]
        if '\r' in s:
            s = s.rsplit('\r', 1)[-1]
        return s

    @classmethod
    def _is_status(cls, s: str) -> bool:
        return bool(s) and bool(cls.STATUS_RE.match(s))

    def _delete_pending(self):
        if self.has_pending:
            try:
                self.widget.delete('pend_mark', 'end-1c')
            except Exception:
                pass
            self.has_pending = False
            self._pending_held = False

    def _commit_pending(self):
        if self.has_pending:
            self.widget.insert('end-1c', '\n')
            self.has_pending = False
            self._pending_held = False

    def _show_pending(self, s: str, held: bool = False):
        if self.has_pending:
            try:
                self.widget.delete('pend_mark', 'end-1c')
            except Exception:
                pass
        else:
            self.widget.mark_set('pend_mark', 'end-1c')
            self.widget.mark_gravity('pend_mark', 'left')
        if s:
            self.widget.insert('end-1c', s)
            self.has_pending = True
            self._pending_held = held

    def _follow_tail(self):
        """仅当视图位于底部时自动跟随最新内容; 用户向上翻动时不强制滚动"""
        try:
            first, last = self.widget.yview()
        except Exception:
            return
        if last >= 0.999:
            self.widget.see('end')

    def flush(self):
        with self._lock:
            if not self.raw:
                return
            segments = self.raw.split('\n')
            complete, tail = segments[:-1], segments[-1]
            self.raw = tail

            if complete and self.has_pending and not self._pending_held:
                self._delete_pending()

            for line in complete:
                cleaned = self._clean(line)
                if self._is_status(cleaned):
                    if self._pending_held:
                        self._show_pending(cleaned, held=True)
                    else:
                        self._commit_pending()
                        self._show_pending(cleaned, held=True)
                else:
                    self._commit_pending()
                    self.widget.insert('end-1c', cleaned + '\n')

            tail_cleaned = self._clean(tail)
            if tail:
                if self.has_pending and self._pending_held:
                    if self._is_status(tail_cleaned):
                        self._show_pending(tail_cleaned, held=False)
                    else:
                        self._commit_pending()
                        self._show_pending(tail_cleaned, held=False)
                else:
                    self._show_pending(tail_cleaned, held=False)
            self._follow_tail()

    def finalize(self):
        with self._lock:
            if self.raw:
                line = self._clean(self.raw)
                if line:
                    self._delete_pending()
                    self.widget.insert('end-1c', line + '\n')
                self.raw = ""
            if self.has_pending:
                self._commit_pending()
            self._follow_tail()


class WizardApp:
    """向导式GUI主程序"""

    APP_VERSION = "1.9.0"

    STEP_TITLES = [
        "SSH连接",
        "创建任务",
    ]

    # 测试用例表格可双击编辑的字段 (列号 -> TestCase属性)
    TEST_TREE_EDITABLE_FIELDS = {
        '#2': 'input_len',
        '#3': 'output_len',
        '#4': 'data_num_recommended',
        '#5': 'prefix_num',
        '#7': 'concurrency_recommended',
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AISBenchPrefixTools")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=COLOR_BG)

        # 设置窗口图标
        icon_path = os.path.join(
            getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
            "app.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        # 点击窗口×按钮时同样走环境清理检查
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)

        # 核心组件
        self.ssh = SSHManager()
        self.docker: Optional[DockerManager] = None
        self.config_mgr: Optional[ConfigManager] = None
        self.designer = TestDesigner()

        # 用户偏好: 界面语言(中文/English)
        self.settings = load_settings()
        language_code = str(self.settings.get("language", "zh"))
        self.language_var = tk.StringVar(value=SUPPORTED_LANGUAGES.get(language_code, "中文"))
        set_language(language_code)

        # 状态变量
        self.current_step = 0
        self.config_data = {}
        self.remote_tar_path = ""
        self.remote_images = []
        self.remote_image_filter_var = tk.StringVar()
        self.deployed = False
        self.image_source_var = tk.StringVar(value="existing")
        self.remote_image_var = tk.StringVar()
        # vLLM服务连接参数默认自动生成, 高级场景可展开修改
        self.service_advanced_var = tk.BooleanVar(value=False)
        # 记录当前容器部署时使用的资源, 用于判断能否复用容器直接执行测试
        self.deployed_model_path = ""
        self.deployed_image = ""

        # 日志处理器 + 取消标志（解决后台线程阻塞UI）
        self._cancel_flag = threading.Event()
        self._flush_timer_id = None
        self._exec_flush_timer_id = None
        self.model_path_var = tk.StringVar()
        self.host_ip_var = tk.StringVar()
        self.host_port_var = tk.StringVar(value="8000")
        self.model_name_var = tk.StringVar(value="ds")
        self.api_key_var = tk.StringVar()
        self.pod_info_var = tk.StringVar()
        self.dataset_path_var = tk.StringVar()

        # 测试用例相关变量
        self.kv_cache_var = tk.StringVar()
        self.dp_var = tk.StringVar(value="1")
        self.max_req_len_var = tk.StringVar()
        self.repeat_rate_var = tk.StringVar(value="0.9")
        self.request_rate_var = tk.StringVar(value="0")
        # KV cache 查询命令 (可复制; 从日志工具筛选后自动更新为实际命令)
        self.kv_grep_cmd_var = tk.StringVar(value=KV_GREP_COMMAND)
        self.input_length_vars = {}
        self.output_length_vars = {}

        self._build_ui()

        # 日志处理器 (部署日志/执行日志, 处理\r进度条单行刷新)
        self._docker_log_handler = LiveLogHandler(self.docker_log)
        self._exec_log_handler = LiveLogHandler(self.exec_log)

    # ============================================================
    #  UI构建
    # ============================================================

    def _build_ui(self):
        """构建主界面"""
        # 主容器
        main_frame = tk.Frame(self.root, bg=COLOR_BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self.main_frame = main_frame

        # 左侧步骤导航
        self._build_sidebar(main_frame)

        # 右侧内容区
        content_frame = tk.Frame(main_frame, bg=COLOR_BG)
        content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self._build_content_area(content_frame)

    def _build_sidebar(self, parent):
        """构建左侧步骤栏"""
        sidebar = tk.Frame(parent, bg=COLOR_CARD, width=200, relief=tk.SOLID, bd=1)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        sidebar.pack_propagate(False)

        # 标题
        title_lbl = LocalizedLabel(sidebar, text="AISBench\nPrefixTools", bg=COLOR_CARD,
                            fg=COLOR_PRIMARY, font=("Segoe UI", 14, "bold"),
                            justify=tk.LEFT)
        title_lbl.pack(padx=16, pady=(20, 16), anchor=tk.W)

        # 步骤按钮
        self.step_buttons = []
        for i, title in enumerate(self.STEP_TITLES):
            btn_frame = tk.Frame(sidebar, bg=COLOR_CARD)
            btn_frame.pack(fill=tk.X, padx=8, pady=2)

            indicator = LocalizedLabel(btn_frame, text="○", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                font=("Segoe UI", 12))
            indicator.pack(side=tk.LEFT, padx=(8, 6))

            label = LocalizedLabel(btn_frame, text=f"{i+1}. {title}", bg=COLOR_CARD,
                           fg=COLOR_TEXT_MUTED, font=("Segoe UI", 10),
                           cursor="hand2")
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 点击跳转
            def _go_to_step(step=i):
                if step <= self._max_reached_step():
                    self._show_step(step)

            label.bind("<Button-1>", lambda e, s=i: _go_to_step(s))
            indicator.bind("<Button-1>", lambda e, s=i: _go_to_step(s))

            self.step_buttons.append((indicator, label))

        # 独立工具: 结果对比分析 (无需连接服务器, 随时可用)
        tools_frame = tk.Frame(sidebar, bg=COLOR_CARD)
        tools_frame.pack(fill=tk.X, padx=8, pady=(18, 0))
        compare_btn = LocalizedLabel(tools_frame, text="📊 结果对比分析",
                               bg="#eff6ff", fg=COLOR_PRIMARY,
                               font=("Segoe UI", 10, "bold"), cursor="hand2",
                               padx=10, pady=6)
        compare_btn.pack(fill=tk.X, ipady=3)
        compare_btn.bind("<Button-1>", lambda _e: self._open_result_compare())
        compare_btn.bind("<Enter>", lambda _e: compare_btn.config(bg="#dbeafe"))
        compare_btn.bind("<Leave>", lambda _e: compare_btn.config(bg="#eff6ff"))
        LocalizedLabel(sidebar, text="无需连接服务器", bg=COLOR_CARD,
                 fg=COLOR_TEXT_MUTED, font=("Segoe UI", 7)
                 ).pack(padx=18, anchor=tk.W)

        # 界面语言切换
        lang_frame = tk.Frame(sidebar, bg=COLOR_CARD)
        lang_frame.pack(fill=tk.X, padx=8, pady=(14, 0))
        LocalizedLabel(lang_frame, text="语言 / Language:", bg=COLOR_CARD,
                       fg=COLOR_TEXT, font=("Segoe UI", 9)
                       ).pack(anchor=tk.W)
        self.language_combo = ttk.Combobox(
            lang_frame,
            textvariable=self.language_var,
            values=list(SUPPORTED_LANGUAGES.values()),
            state="readonly",
            width=12,
            font=("Segoe UI", 9),
        )
        self.language_combo.pack(fill=tk.X, pady=(2, 0))
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_change)

        # 底部状态
        tk.Frame(sidebar, bg=COLOR_BORDER, height=1).pack(fill=tk.X, padx=12, pady=12)
        self.status_lbl = LocalizedLabel(sidebar, text="● 未连接", bg=COLOR_CARD,
                                   fg=COLOR_ERROR, font=("Segoe UI", 9))
        self.status_lbl.pack(padx=16, pady=(0, 16), anchor=tk.W)

    def _max_reached_step(self):
        """返回用户可达到的最大步骤"""
        return self.current_step

    def _on_language_change(self, _event=None):
        """切换界面语言并立即重建界面"""
        selected = self.language_var.get().strip()
        code = next((key for key, label in SUPPORTED_LANGUAGES.items()
                     if label == selected), "zh")
        if code == get_language():
            return
        set_language(code)
        self.settings["language"] = code
        save_settings(self.settings)
        self._rebuild_ui_for_language()

    def _rebuild_ui_for_language(self):
        """按当前语言重建主界面(完整保留步骤、输入与结果状态)"""
        self.language_var.set(SUPPORTED_LANGUAGES.get(get_language(), "中文"))

        # ---- 切换前快照: 所有用户输入 / 状态 / 结果 ----
        snapshot = {}
        if hasattr(self, "docker_log"):
            snapshot["docker_log"] = self.docker_log.get("1.0", "end-1c")
        if hasattr(self, "exec_log"):
            snapshot["exec_log"] = self.exec_log.get("1.0", "end-1c")
        if hasattr(self, "conn_vars"):
            snapshot["conn_values"] = {
                k: v.get() for k, v in self.conn_vars.items()}
        if hasattr(self, "conn_password"):
            snapshot["conn_password"] = self.conn_password.get()
        if hasattr(self, "conn_key"):
            snapshot["conn_key"] = self.conn_key.get()
        if hasattr(self, "conn_status_lbl"):
            snapshot["conn_status"] = (
                self.conn_status_lbl.cget("text"), self.conn_status_lbl.cget("fg"))
        if hasattr(self, "remote_images") and self.remote_images:
            snapshot["remote_images"] = [
                dict(item) for item in self.remote_images]
        if hasattr(self, "remote_image_filter_var"):
            snapshot["remote_image_filter"] = (
                self.remote_image_filter_var.get())
        if hasattr(self, "image_list_status"):
            snapshot["image_status"] = (
                self.image_list_status.cget("text"), self.image_list_status.cget("fg"))
        if hasattr(self, "tar_path"):
            snapshot["tar_path"] = self.tar_path.get()
        if hasattr(self, "zip_path"):
            snapshot["zip_path"] = self.zip_path.get()
        if hasattr(self, "work_dir_var"):
            snapshot["work_dir"] = self.work_dir_var.get()
        if hasattr(self, "work_dir_status"):
            snapshot["work_dir_status"] = (
                self.work_dir_status.cget("text"), self.work_dir_status.cget("fg"))
        if hasattr(self, "docker_info_labels"):
            snapshot["docker_info"] = {
                k: lbl.cget("text")
                for k, lbl in self.docker_info_labels.items()}
        if hasattr(self, "deploy_btn"):
            snapshot["deploy_text"] = self.deploy_btn.cget("text")
        if hasattr(self, "create_task_btn"):
            snapshot["create_task_text"] = self.create_task_btn.cget("text")
        if hasattr(self, "code_source_var"):
            snapshot["code_source"] = self.code_source_var.get()
        if self.input_length_vars:
            snapshot["input_lengths"] = {
                length: var.get()
                for length, var in self.input_length_vars.items()}
        if self.output_length_vars:
            snapshot["output_lengths"] = {
                length: var.get()
                for length, var in self.output_length_vars.items()}
        if hasattr(self, "residual_status_lbl"):
            snapshot["residual_status"] = (
                self.residual_status_lbl.cget("text"),
                self.residual_status_lbl.cget("fg"))
        if hasattr(self, "test_tree"):
            snapshot["test_rows"] = [
                self.test_tree.item(iid)["values"]
                for iid in self.test_tree.get_children()
            ]
        if hasattr(self, "results_tree"):
            snapshot["result_rows"] = [
                self.results_tree.item(iid)["values"]
                for iid in self.results_tree.get_children()
            ]
        if hasattr(self, "results_info_lbl"):
            snapshot["results_info"] = self.results_info_lbl.cget("text")
        if hasattr(self, "calc_detail_text"):
            snapshot["calc_detail"] = self.calc_detail_text.get("1.0", "end-1c")
        if hasattr(self, "commands_text"):
            snapshot["commands"] = self.commands_text.get("1.0", "end-1c")
        if hasattr(self, "summary_text"):
            snapshot["summary"] = self.summary_text.cget("text")
        if hasattr(self, "local_output_var"):
            snapshot["local_output"] = self.local_output_var.get()
        if hasattr(self, "deployed"):
            snapshot["deployed"] = self.deployed
        if hasattr(self, "_content_canvas"):
            snapshot["scroll"] = self._content_canvas.yview()

        if hasattr(self, "main_frame"):
            self.main_frame.destroy()
        try:
            self.root.unbind_all("<MouseWheel>")
        except Exception:
            pass

        self._build_ui()
        self._docker_log_handler = LiveLogHandler(self.docker_log)
        self._exec_log_handler = LiveLogHandler(self.exec_log)

        # ---- 恢复日志 ----
        if snapshot.get("docker_log"):
            self.docker_log.insert("1.0", snapshot["docker_log"])
        if snapshot.get("exec_log"):
            self.exec_log.insert("1.0", snapshot["exec_log"])

        # ---- 恢复步骤1: SSH连接信息 ----
        if snapshot.get("conn_values"):
            for key, value in snapshot["conn_values"].items():
                if key in self.conn_vars:
                    self.conn_vars[key].set(value)
        if "conn_password" in snapshot:
            self.conn_password.set(snapshot["conn_password"])
        if "conn_key" in snapshot:
            self.conn_key.set(snapshot["conn_key"])
        if snapshot.get("conn_status"):
            text, color = snapshot["conn_status"]
            self.conn_status_lbl.config(text=text, fg=color)

        # ---- 恢复任务页: 镜像/代码/模型/部署状态 ----
        if snapshot.get("remote_images"):
            self.remote_images = snapshot["remote_images"]
            if "remote_image_filter" in snapshot:
                self.remote_image_filter_var.set(
                    snapshot["remote_image_filter"])
            else:
                self._apply_remote_image_filter(update_selection=False)
        if "code_source" in snapshot and hasattr(self, "code_source_var"):
            self.code_source_var.set(snapshot["code_source"])
        self._on_image_source_change()
        self._on_code_source_change()
        if "tar_path" in snapshot:
            self.tar_path.set(snapshot["tar_path"])
        if "zip_path" in snapshot:
            self.zip_path.set(snapshot["zip_path"])
        if "work_dir" in snapshot:
            self.work_dir_var.set(snapshot["work_dir"])
        if snapshot.get("work_dir_status"):
            text, color = snapshot["work_dir_status"]
            self.work_dir_status.config(text=text, fg=color)
        if snapshot.get("docker_info"):
            for key, text in snapshot["docker_info"].items():
                if key in self.docker_info_labels:
                    self.docker_info_labels[key].config(text=text)
        if snapshot.get("image_status"):
            text, color = snapshot["image_status"]
            self.image_list_status.config(text=text, fg=color)
        if snapshot.get("deploy_text"):
            self.deploy_btn.config(text=snapshot["deploy_text"])
        if snapshot.get("create_task_text"):
            self.create_task_btn.config(text=snapshot["create_task_text"])

        # ---- 恢复测试用例与计算明细 ----
        if snapshot.get("test_rows"):
            for values in snapshot["test_rows"]:
                self.test_tree.insert("", tk.END, values=values)
        if "input_lengths" in snapshot:
            for length, value in snapshot["input_lengths"].items():
                if length in self.input_length_vars:
                    self.input_length_vars[length].set(value)
        if "output_lengths" in snapshot:
            for length, value in snapshot["output_lengths"].items():
                if length in self.output_length_vars:
                    self.output_length_vars[length].set(value)
        # 计算明细按当前语言重新渲染, 避免语言切换后保留旧语言文本
        if self.designer.test_cases:
            self._show_calc_details()
        elif "calc_detail" in snapshot and snapshot["calc_detail"]:
            self.calc_detail_text.insert("1.0", snapshot["calc_detail"])

        # ---- 恢复命令/结果 ----
        if "commands" in snapshot and snapshot["commands"]:
            self.commands_text.insert("1.0", snapshot["commands"])
        if snapshot.get("summary"):
            self.summary_text.config(text=snapshot["summary"])
        if self.designer.test_cases:
            # 摘要同样按当前语言重新渲染
            self.summary_text.config(text=self.designer.get_summary())
        if snapshot.get("result_rows"):
            for values in snapshot["result_rows"]:
                self.results_tree.insert("", tk.END, values=values)
        if snapshot.get("results_info"):
            self.results_info_lbl.config(text=snapshot["results_info"])
        if "local_output" in snapshot:
            self.local_output_var.set(snapshot["local_output"])

        # ---- 恢复侧边栏/残留容器状态 ----
        if self.ssh.connected:
            self.status_lbl.config(text="● 已连接", fg=COLOR_SUCCESS)
        if snapshot.get("residual_status"):
            text, color = snapshot["residual_status"]
            self.residual_status_lbl.config(text=text, fg=color)
        if self.docker and self.docker.container_name:
            self.cleanup_btn.config(state=tk.NORMAL)

        # ---- 回到原步骤(不跳转) 并恢复滚动位置 ----
        self._show_step(self.current_step)
        if snapshot.get("scroll") and hasattr(self, "_content_canvas"):
            self._content_canvas.yview_moveto(snapshot["scroll"][0])
        self.root.update_idletasks()

    def _build_content_area(self, parent):
        """构建右侧内容区 (可滚动 + 导航栏固定底部)"""
        # 导航栏 (固定在底部)
        nav_frame = tk.Frame(parent, bg=COLOR_BG)
        nav_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        self.prev_btn = LocalizedTtkButton(nav_frame, text="< 上一步", command=self._prev_step)
        self.prev_btn.pack(side=tk.LEFT)

        self.next_btn = LocalizedTtkButton(nav_frame, text="下一步 >", command=self._next_step,
                                   style="Accent.TButton")
        self.next_btn.pack(side=tk.RIGHT)

        # 可滚动内容容器
        scrollbar = tk.Scrollbar(parent, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._content_canvas = tk.Canvas(parent, bg=COLOR_BG, highlightthickness=0,
                                         yscrollcommand=scrollbar.set)
        self._content_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._content_canvas.yview)

        self.content_container = tk.Frame(self._content_canvas, bg=COLOR_BG)
        self._content_canvas.create_window((0, 0), window=self.content_container,
                                           anchor='nw', tags='inner')

        self._viewport_h = 0
        self._forced_h = 0

        # 内容不足一屏时撑满画布高度, 使 fill=BOTH/expand 的组件
        # (如各步骤日志栏) 能随窗口弹性伸缩; 超出一屏时保持自然高度可滚动
        def _apply_content_size():
            req = self.content_container.winfo_reqheight()
            target = max(req, self._viewport_h)
            if target != self._forced_h:
                self._forced_h = target
                self._content_canvas.itemconfig('inner', height=target)
            self._content_canvas.configure(
                scrollregion=self._content_canvas.bbox('all'))

        self._apply_content_size = _apply_content_size

        def _on_content_configure(_event):
            _apply_content_size()

        def _on_canvas_configure(_event):
            self._content_canvas.itemconfig('inner', width=_event.width)
            self._viewport_h = _event.height
            _apply_content_size()

        self.content_container.bind('<Configure>', _on_content_configure)
        self._content_canvas.bind('<Configure>', _on_canvas_configure)

        # 全局滚轮: 指针位于日志/表格等可滚动组件上时优先滚动其自身,
        # 到达边界或指针位于普通区域时滚动整个步骤页面
        self._content_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # 为每个步骤创建Frame
        self.step_frames = []
        for i in range(len(self.STEP_TITLES)):
            frame = tk.Frame(self.content_container, bg=COLOR_BG)
            self.step_frames.append(frame)

        # 构建各步骤内容
        self._build_step0_connection()
        # 步骤2"创建任务": 原 部署/配置/用例/执行 四个步骤合并为一页
        self._build_task_resources_section()
        self._build_task_testcases_section()
        self._build_task_run_section()
        self._build_task_execute_section()

        # 首次构建显示第1步; 语言切换重建时保持当前步骤(由调用方恢复)
        if not hasattr(self, "current_step"):
            self.current_step = 0
        self._show_step(self.current_step)

    def _on_mousewheel(self, event):
        """全局滚轮: 指针下可滚动组件优先, 滚到边界后滚动整页"""
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        # Windows高精度滚轮/触控板会产生小于120的delta,
        # int(delta/120)会被截断为0导致"滚动条按钮可拖动但滚轮不生效"。
        # 对小于120的delta按方向滚动1个单位, 常规±120鼠标保持原行为。
        if abs(delta) >= 120:
            units = int(-delta / 120)
        else:
            units = -1 if delta > 0 else 1
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        target = None
        while widget is not None and widget is not self._content_canvas:
            if isinstance(widget, (tk.Text, ttk.Treeview, tk.Listbox)):
                target = widget
                break
            widget = widget.master

        if target is not None:
            first, last = target.yview()
            if (delta > 0 and first > 0.0) or \
               (delta < 0 and last < 1.0):
                # 组件自身可继续滚动; 事件已由其默认绑定处理时避免重复滚动
                if event.widget is not target:
                    target.yview_scroll(units, "units")
                return

        self._content_canvas.yview_scroll(units, "units")

    def _build_step_header(self, parent, title, desc=""):
        """构建步骤标题"""
        header = tk.Frame(parent, bg=COLOR_BG)
        header.pack(fill=tk.X, pady=(0, 12))

        LocalizedLabel(header, text=title, bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        if desc:
            LocalizedLabel(header, text=desc, bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
                   font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(2, 0))

    def _build_section_header(self, parent, number, title, desc=""):
        """构建"创建任务"页内的分区标题(带编号徽标, 让合并后的单页结构清晰)"""
        header = tk.Frame(parent, bg=COLOR_BG)
        header.pack(fill=tk.X, pady=(14, 4))

        badge = tk.Label(header, text=str(number), bg=COLOR_PRIMARY, fg="white",
                         font=("Segoe UI", 10, "bold"), width=2, relief=tk.FLAT)
        badge.pack(side=tk.LEFT, padx=(0, 8), ipady=2)

        title_box = tk.Frame(header, bg=COLOR_BG)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        LocalizedLabel(title_box, text=title, bg=COLOR_BG, fg=COLOR_TEXT,
                       font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        if desc:
            LocalizedLabel(title_box, text=desc, bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
                           font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(2, 0))
        return header

    # ============================================================
    #  Step 0: SSH连接
    # ============================================================

    def _build_step0_connection(self):
        frame = self.step_frames[0]

        self._build_step_header(frame, "步骤 1: SSH连接到执行机",
                               "输入远程执行机的SSH连接信息")

        form = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        form.pack(fill=tk.X, pady=8)

        fields = [
            ("执行机 IP *", "host", ""),
            ("SSH 端口", "port", "22"),
            ("用户名 *", "user", "root"),
        ]
        self.conn_vars = {}
        for i, (label, key, default) in enumerate(fields):
            LocalizedLabel(form, text=label, bg=COLOR_CARD, fg=COLOR_TEXT,
                   font=("Segoe UI", 9)).grid(row=i, column=0, sticky=tk.W,
                                               padx=16, pady=8)
            var = tk.StringVar(value=default)
            self.conn_vars[key] = var
            entry = tk.Entry(form, textvariable=var, width=30, font=("Segoe UI", 9))
            entry.grid(row=i, column=1, padx=16, pady=8, sticky=tk.W)

        LocalizedLabel(form, text="密码", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=3, column=0, sticky=tk.W, padx=16, pady=8)
        self.conn_password = tk.StringVar()
        pw_frame = tk.Frame(form, bg=COLOR_CARD)
        pw_frame.grid(row=3, column=1, padx=16, pady=8, sticky=tk.W)
        pw_entry = tk.Entry(pw_frame, textvariable=self.conn_password, width=30,
                          show="*", font=("Segoe UI", 9))
        pw_entry.pack(side=tk.LEFT)

        def _toggle_pw():
            if pw_entry.cget('show') == '*':
                pw_entry.config(show='')
                pw_eye_btn.config(text='🙈')
            else:
                pw_entry.config(show='*')
                pw_eye_btn.config(text='👁')

        pw_eye_btn = LocalizedButton(pw_frame, text='👁', font=("Segoe UI", 8),
                               width=3, relief=tk.FLAT, bg=COLOR_CARD,
                               fg=COLOR_TEXT_MUTED, command=_toggle_pw)
        pw_eye_btn.pack(side=tk.LEFT, padx=(4, 0))

        LocalizedLabel(form, text="或密钥文件路径", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=4, column=0, sticky=tk.W, padx=16, pady=8)
        key_frame = tk.Frame(form, bg=COLOR_CARD)
        key_frame.grid(row=4, column=1, padx=16, pady=8, sticky=tk.W)
        self.conn_key = tk.StringVar()
        tk.Entry(key_frame, textvariable=self.conn_key, width=22,
               font=("Segoe UI", 9)).pack(side=tk.LEFT)
        LocalizedButton(key_frame, text="浏览...", command=self._browse_key_file,
                font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        # 连接按钮
        btn_frame = tk.Frame(frame, bg=COLOR_BG)
        btn_frame.pack(fill=tk.X, pady=12)

        self.connect_btn = LocalizedButton(btn_frame, text="测试连接", bg=COLOR_PRIMARY,
                                    fg="white", font=("Segoe UI", 9, "bold"),
                                    relief=tk.FLAT, padx=16, pady=4,
                                    command=self._test_connection)
        self.connect_btn.pack(side=tk.LEFT)

        self.conn_status_lbl = LocalizedLabel(btn_frame, text="", bg=COLOR_BG,
                                        fg=COLOR_TEXT_MUTED, font=("Segoe UI", 9))
        self.conn_status_lbl.pack(side=tk.LEFT, padx=12)

    def _browse_key_file(self):
        path = filedialog.askopenfilename(
            title=tr("选择SSH密钥文件"),
            filetypes=[("All files", "*.*"), ("PEM files", "*.pem")]
        )
        if path:
            self.conn_key.set(path)

    def _test_connection(self):
        host = self.conn_vars["host"].get().strip()
        port = int(self.conn_vars["port"].get().strip() or "22")
        user = self.conn_vars["user"].get().strip()
        password = self.conn_password.get().strip() or None
        key_path = self.conn_key.get().strip() or None

        if not host or not user:
            showwarning("提示", "请填写IP和用户名")
            return
        if not password and not key_path:
            showwarning("提示", "请填写密码或密钥文件路径")
            return

        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self.conn_status_lbl.config(text="正在连接...", fg=COLOR_WARNING)

        def _do_connect():
            ok, msg = self.ssh.connect(host, port, user, password, key_path)
            self.root.after(0, lambda: self._on_connect_result(ok, msg))

        threading.Thread(target=_do_connect, daemon=True).start()

    def _on_connect_result(self, ok, msg):
        self.connect_btn.config(state=tk.NORMAL, text="测试连接")
        if ok:
            self.conn_status_lbl.config(text=msg, fg=COLOR_SUCCESS)
            self.status_lbl.config(text="● 已连接", fg=COLOR_SUCCESS)
            self.host_ip_var.set(self.conn_vars["host"].get().strip())
            showinfo("成功", msg)
            # 连接成功后自动扫描上次退出可能遗留的容器
            self._start_residual_scan(prompt_if_found=True)
        else:
            self.conn_status_lbl.config(text=msg, fg=COLOR_ERROR)
            showerror("连接失败", msg)

    # ============================================================
    #  创建任务 - 分区1: 任务资源(镜像/代码/模型)
    # ============================================================

    def _build_task_resources_section(self):
        frame = self.step_frames[1]

        self._build_step_header(
            frame, "步骤 2: 创建任务",
            "配置测试资源与测试用例后, 一键完成容器部署、配置写入与测试执行")
        self.resources_section_header = self._build_section_header(
            frame, 1, "任务资源（镜像 · 代码 · 模型）",
            "选择AISBench镜像与测试代码来源, 并指定模型权重路径; vLLM服务参数默认自动生成, 可展开高级设置修改")

        form = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        form.pack(fill=tk.X, pady=8)

        row = 0

        # AISBench镜像来源: 优先复用执行机已有镜像; 没有可用镜像时再上传tar包
        LocalizedLabel(form, text="AISBench 镜像来源:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W, padx=16, pady=8)
        source_frame = tk.Frame(form, bg=COLOR_CARD)
        source_frame.grid(row=row, column=1, columnspan=2,
                          padx=16, pady=(8, 2), sticky=tk.W)
        LocalizedRadiobutton(source_frame, text="执行机已有镜像", variable=self.image_source_var,
                       value="existing", bg=COLOR_CARD, font=("Segoe UI", 9),
                       command=self._on_image_source_change).pack(side=tk.LEFT)
        LocalizedRadiobutton(source_frame, text="上传本地镜像tar包", variable=self.image_source_var,
                       value="upload", bg=COLOR_CARD, font=("Segoe UI", 9),
                       command=self._on_image_source_change).pack(side=tk.LEFT, padx=(12, 0))

        row += 1

        # 已有镜像选择 / 本地tar上传 (同格切换显示)
        image_choice_frame = tk.Frame(form, bg=COLOR_CARD)
        image_choice_frame.grid(row=row, column=1, columnspan=2,
                                padx=16, pady=(0, 8), sticky=tk.EW)
        # 让内部唯一列可伸缩: 输入框随窗口伸缩, 按钮不被顶出界面
        image_choice_frame.columnconfigure(0, weight=1, minsize=0)
        self.remote_image_frame = tk.Frame(image_choice_frame, bg=COLOR_CARD)
        self.remote_image_frame.grid(row=0, column=0, sticky=tk.EW)
        remote_combo_row = tk.Frame(self.remote_image_frame, bg=COLOR_CARD)
        remote_combo_row.pack(fill=tk.X)
        # 镜像关键字筛选: 镜像较多时按名称子串过滤, 不区分大小写
        LocalizedLabel(remote_combo_row, text=tr("筛选:"),
                       bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                       font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 2))
        self.remote_image_filter_entry = tk.Entry(
            remote_combo_row, textvariable=self.remote_image_filter_var,
            width=12, font=("Segoe UI", 8))
        self.remote_image_filter_entry.pack(side=tk.LEFT, padx=(0, 6))
        self.remote_image_filter_var.trace_add(
            "write", lambda *_args: self._apply_remote_image_filter())
        # width=1: minimal requested width; fill=X expands it to the
        # available width so long image names scroll inside instead of
        # pushing the buttons out of the window.
        self.remote_image_combo = ttk.Combobox(remote_combo_row,
                                               textvariable=self.remote_image_var,
                                               width=1, font=("Segoe UI", 9),
                                               state="readonly")
        self.remote_image_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.remote_image_combo.bind("<<ComboboxSelected>>", self._on_remote_image_selected)
        LocalizedButton(remote_combo_row, text="查看已有镜像", font=("Segoe UI", 8),
                  command=self._refresh_remote_images).pack(side=tk.LEFT, padx=(4, 0))

        self.tar_upload_frame = tk.Frame(image_choice_frame, bg=COLOR_CARD)
        self.tar_upload_frame.grid(row=0, column=0, sticky=tk.EW)
        self.tar_upload_frame.grid_remove()
        self.tar_path = tk.StringVar()
        tk.Entry(self.tar_upload_frame, textvariable=self.tar_path, width=1,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        LocalizedButton(self.tar_upload_frame, text="浏览...", command=self._browse_tar,
                  font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))
        LocalizedButton(self.tar_upload_frame, text="镜像下载链接", command=lambda: self._open_link(
                "https://github.com/AISBench/benchmark/releases/tag/v3.1-20261013-master"),
                font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        self.image_list_status = LocalizedLabel(image_choice_frame, text="尚未查询",
                                          bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                          font=("Segoe UI", 8), anchor=tk.W)
        self.image_list_status.grid(row=1, column=0, sticky=tk.EW, pady=(2, 0))

        self.remote_image_filter_hint = LocalizedLabel(
            image_choice_frame, text="", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 7), anchor=tk.W)
        self.remote_image_filter_hint.grid(
            row=2, column=0, sticky=tk.EW, pady=(0, 2))

        row += 1

        # 测试代码来源: 程序内置 / 本地zip包
        LocalizedLabel(form, text="测试代码来源:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W, padx=16, pady=8)
        source_frame = tk.Frame(form, bg=COLOR_CARD)
        source_frame.grid(row=row, column=1, columnspan=2, padx=16, pady=(8, 2), sticky=tk.W)

        self.code_source_var = tk.StringVar(value="builtin")
        LocalizedRadiobutton(source_frame, text="程序内置", variable=self.code_source_var,
                       value="builtin", bg=COLOR_CARD, font=("Segoe UI", 9),
                       command=self._on_code_source_change).pack(side=tk.LEFT)
        LocalizedRadiobutton(source_frame, text="本地zip包", variable=self.code_source_var,
                       value="zip", bg=COLOR_CARD, font=("Segoe UI", 9),
                       command=self._on_code_source_change).pack(side=tk.LEFT, padx=(12, 0))

        row += 1

        # 内置代码状态 / zip选择 (同格切换显示)
        self.code_builtin_frame = tk.Frame(form, bg=COLOR_CARD)
        self.code_builtin_frame.grid(row=row, column=1, columnspan=2,
                                     padx=16, pady=(0, 8), sticky=tk.EW)
        code_dir = self._get_bundled_code_dir()
        code_desc = "aisbench_auto_tools_prefix (程序内置, 部署时自动上传)" \
            if os.path.isdir(code_dir) else "未找到内置代码! 请改用本地zip包"
        LocalizedLabel(self.code_builtin_frame, text=code_desc,
                 bg=COLOR_CARD, fg=(COLOR_TEXT if os.path.isdir(code_dir) else COLOR_ERROR),
                 font=("Segoe UI", 8), anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.code_zip_frame = tk.Frame(form, bg=COLOR_CARD)
        self.code_zip_frame.grid(row=row, column=1, columnspan=2,
                                 padx=16, pady=(0, 8), sticky=tk.EW)
        self.code_zip_frame.grid_remove()
        self.zip_path = tk.StringVar()
        tk.Entry(self.code_zip_frame, textvariable=self.zip_path, width=1,
               font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        LocalizedButton(self.code_zip_frame, text="浏览...", command=self._browse_zip,
                font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))
        LocalizedButton(self.code_zip_frame, text="代码下载链接", command=lambda: self._open_link(
                "https://github.com/rayn-zzz/aisbench_auto_tools_prefix"),
                font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        row += 1

        # 模型路径（下拉框 + 浏览）
        LocalizedLabel(form, text="模型权重路径 (远程主机):", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W, padx=16, pady=8)
        model_frame = tk.Frame(form, bg=COLOR_CARD)
        model_frame.grid(row=row, column=1, columnspan=2, padx=16, pady=8, sticky=tk.EW)
        self.model_combo = ttk.Combobox(model_frame, textvariable=self.model_path_var,
                                        width=1, font=("Segoe UI", 9))
        self.model_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        LocalizedButton(model_frame, text="浏览远程目录", command=self._browse_remote_model,
                font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        row += 1

        # vLLM服务连接: 默认自动生成(模型名ds/执行机IP/端口8000), 高级场景可展开修改
        service_row = tk.Frame(form, bg=COLOR_CARD)
        service_row.grid(row=row, column=0, columnspan=3, sticky=tk.EW,
                         padx=16, pady=(0, 2))
        LocalizedLabel(service_row, text="vLLM服务连接:", bg=COLOR_CARD,
                       fg=COLOR_TEXT, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.service_summary_lbl = LocalizedLabel(
            service_row, text="", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 8))
        self.service_summary_lbl.pack(side=tk.LEFT, padx=(8, 4))
        self.service_toggle_btn = LocalizedButton(
            service_row, text="高级设置 ▾", font=("Segoe UI", 8),
            relief=tk.FLAT, bg="#f0f5ff", fg=COLOR_PRIMARY, padx=8,
            command=self._toggle_service_advanced)
        self.service_toggle_btn.pack(side=tk.LEFT)

        row += 1
        # 高级服务配置(默认折叠): 模型名称/服务IP/端口/API Key/POD_INFO
        self.service_advanced_frame = tk.Frame(form, bg="#f8fafc",
                                                relief=tk.SOLID, bd=1)
        self.service_advanced_frame.grid(row=row, column=0, columnspan=3,
                                         sticky=tk.EW, padx=16, pady=(0, 8))
        service_fields = [
            ("模型名称 (--served-model-name):", "model_name_var"),
            ("vLLM服务 IP:", "host_ip_var"),
            ("vLLM服务端口:", "host_port_var"),
            ("API Key (鉴权, 可选):", "api_key_var"),
            ("POD_INFO (多DP必填, 格式: ip:port,ip:port):", "pod_info_var"),
        ]
        for i, (label, var_name) in enumerate(service_fields):
            LocalizedLabel(self.service_advanced_frame, text=label, bg="#f8fafc",
                           fg=COLOR_TEXT, font=("Segoe UI", 8)
                           ).grid(row=i, column=0, sticky=tk.W, padx=12, pady=3)
            tk.Entry(self.service_advanced_frame,
                     textvariable=getattr(self, var_name), width=32,
                     font=("Segoe UI", 8)
                     ).grid(row=i, column=1, padx=12, pady=3, sticky=tk.EW)
        self.service_advanced_frame.columnconfigure(1, weight=1)
        LocalizedLabel(
            self.service_advanced_frame,
            text="留空时自动使用: 模型名称ds · IP=执行机IP · 端口8000",
            bg="#f8fafc", fg=COLOR_TEXT_MUTED, font=("Segoe UI", 7)
        ).grid(row=len(service_fields), column=0, columnspan=2,
               sticky=tk.W, padx=12, pady=(2, 6))
        if self.service_advanced_var.get():
            self.service_advanced_frame.grid()
        else:
            self.service_advanced_frame.grid_remove()

        # 服务参数摘要与高级区可见性随语言重建恢复
        self._update_service_summary()
        for var in (self.model_name_var, self.host_ip_var, self.host_port_var):
            var.trace_add("write", lambda *_args: self._update_service_summary())

        form.columnconfigure(1, weight=1)

    def _toggle_service_advanced(self):
        """展开/折叠vLLM服务连接高级设置"""
        visible = not self.service_advanced_var.get()
        self.service_advanced_var.set(visible)
        if visible:
            self.service_advanced_frame.grid()
            self.service_toggle_btn.config(text="收起 ▴")
        else:
            self.service_advanced_frame.grid_remove()
            self.service_toggle_btn.config(text="高级设置 ▾")

    def _update_service_summary(self):
        """显示自动生成的vLLM服务连接摘要"""
        if not hasattr(self, "service_summary_lbl"):
            return
        host = self.host_ip_var.get().strip()
        if not host and hasattr(self, "conn_vars"):
            host = self.conn_vars["host"].get().strip()
        model = self.model_name_var.get().strip() or "ds"
        port = self.host_port_var.get().strip() or "8000"
        summary = trf("自动: {model} @ {host}:{port} (可展开修改)",
                      model=model, host=host or "-", port=port)
        self.service_summary_lbl.config(text=summary)

    def _on_image_source_change(self):
        """切换镜像来源: 执行机已有镜像 / 本地tar包"""
        if self.image_source_var.get() == "existing":
            self.tar_upload_frame.grid_remove()
            self.remote_image_frame.grid()
            self.remote_image_filter_hint.grid()
        else:
            self.remote_image_frame.grid_remove()
            self.tar_upload_frame.grid()
            self.remote_image_filter_hint.grid_remove()

    def _refresh_remote_images(self):
        """查询并填充执行机上已有的Docker镜像"""
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return

        if not self.docker:
            self.docker = DockerManager(self.ssh)

        self.image_list_status.config(text="正在查询执行机镜像...", fg=COLOR_TEXT_MUTED)
        try:
            images = self.docker.list_images()
        except Exception as e:
            self.remote_images = []
            self.remote_image_combo.config(values=[])
            self.remote_image_var.set("")
            self.image_source_var.set("upload")
            self._on_image_source_change()
            self.image_list_status.config(
                text=trf("查询失败: {error}。可先上传tar包，部署时会检查Docker。", error=e),
                fg=COLOR_ERROR)
            return

        self.remote_images = images
        self._apply_remote_image_filter(update_selection=False)
        names = self.remote_image_combo.cget("values") or []

        if not names:
            if not images:
                self.remote_image_var.set("")
                self.image_source_var.set("upload")
                self._on_image_source_change()
                self.image_list_status.config(
                    text="未发现可用镜像，请上传本地AISBench镜像tar包。",
                    fg=COLOR_WARNING)
            else:
                self.remote_image_var.set("")
                self._update_remote_image_filter_hint()
                self.image_list_status.config(
                    text=trf("未找到匹配当前关键字的镜像，请调整关键字或清空筛选。"),
                    fg=COLOR_WARNING)
            return

        selected = self.remote_image_var.get().strip()
        if selected not in names:
            # 只自动选择名称明显属于AISBench的镜像; 其他镜像交给用户确认
            preferred = next((name for name in names
                              if "aisbench" in name.lower() or "ais-bench" in name.lower()
                              or "benchmark" in name.lower()), "")
            self.remote_image_var.set(preferred)
            selected = preferred
        self.image_source_var.set("existing")
        self._on_image_source_change()
        if selected:
            self._on_remote_image_selected()
        else:
            self.image_list_status.config(
                text=trf("共 {count} 个镜像（筛选后 {shown} 个），请选择AISBench镜像；如无合适镜像，请切换为上传tar包。",
                    count=len(images), shown=len(names)),
                fg=COLOR_WARNING)

    def _apply_remote_image_filter(self, update_selection: bool = True):
        """按关键字筛选已有镜像列表(子串匹配, 不区分大小写)"""
        keyword = self.remote_image_filter_var.get().strip().lower()
        if keyword:
            filtered = [
                item["name"] for item in self.remote_images
                if keyword in item["name"].lower()]
        else:
            filtered = [item["name"] for item in self.remote_images]
        self.remote_image_combo.config(values=filtered)

        if update_selection:
            selected = self.remote_image_var.get().strip()
            if selected and selected not in filtered:
                self.remote_image_var.set("")
                self._on_remote_image_selected()
            self._update_remote_image_filter_hint()

    def _update_remote_image_filter_hint(self):
        """显示筛选结果数量提示(未查询或未筛选时隐藏)"""
        keyword = self.remote_image_filter_var.get().strip()
        values = self.remote_image_combo.cget("values") or []
        if not self.remote_images or not keyword:
            self.remote_image_filter_hint.config(text="")
            return
        self.remote_image_filter_hint.config(
            text=trf("筛选: {shown}/{total} 个镜像",
                     shown=len(values), total=len(self.remote_images)))

    def _on_remote_image_selected(self, event=None):
        """更新已选镜像的详情提示"""
        selected = self.remote_image_var.get().strip()
        item = next((img for img in self.remote_images if img["name"] == selected), None)
        if not item:
            self.image_list_status.config(text="请选择执行机上的镜像", fg=COLOR_WARNING)
            return
        detail = trf("ID {id} · 创建于 {created} · 大小 {size}",
                     id=item['id'], created=item['created'], size=item['size'])
        self.image_list_status.config(
            text=trf("已选择 {selected} ({detail})", selected=selected, detail=detail),
            fg=COLOR_SUCCESS)

    def _browse_tar(self):
        path = filedialog.askopenfilename(
            title=tr("选择AISBench镜像包"),
            filetypes=[("tar.gz files", "*.tar.gz"), ("tar files", "*.tar"), ("All files", "*.*")]
        )
        if path:
            self.tar_path.set(path)

    def _get_bundled_code_dir(self) -> str:
        """获取内置的aisbench_auto_tools_prefix代码目录 (兼容PyInstaller冻结环境)"""
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "aisbench_auto_tools_prefix")

    def _on_code_source_change(self):
        """切换测试代码来源: 内置 / 本地zip包"""
        if self.code_source_var.get() == "builtin":
            self.code_zip_frame.grid_remove()
            self.code_builtin_frame.grid()
        else:
            self.code_builtin_frame.grid_remove()
            self.code_zip_frame.grid()

    def _browse_zip(self):
        path = filedialog.askopenfilename(
            title=tr("选择代码zip包"),
            filetypes=[("zip files", "*.zip"), ("All files", "*.*")]
        )
        if path:
            self.zip_path.set(path)

    def _browse_remote_model(self):
        """远程目录浏览对话框"""
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("浏览远程目录 - 选择模型路径")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()

        top = tk.Frame(dialog)
        top.pack(fill=tk.X, padx=8, pady=8)
        LocalizedLabel(top, text="路径:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        path_var = tk.StringVar(value="/")
        path_entry = tk.Entry(top, textvariable=path_var, width=1, font=("Segoe UI", 9))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        LocalizedButton(top, text="前往", font=("Segoe UI", 8),
                 command=lambda: self._list_remote_dir(listbox, path_var, dialog)).pack(side=tk.LEFT)

        list_frame = tk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                           font=("Segoe UI", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        # 双击进入目录
        def _on_double_click(event):
            selection = listbox.curselection()
            if not selection:
                return
            item = listbox.get(selection[0])
            if item == "../ (上级目录)":
                current = path_var.get()
                parent = '/'.join(current.rstrip('/').split('/')[:-1]) or '/'
                path_var.set(parent)
                self._list_remote_dir(listbox, path_var, dialog)
            elif item.startswith("[DIR] "):
                dirname = item[6:]
                current = path_var.get().rstrip('/')
                new_path = current + "/" + dirname if current else "/" + dirname
                path_var.set(new_path)
                self._list_remote_dir(listbox, path_var, dialog)

        listbox.bind("<Double-Button-1>", _on_double_click)

        # 选择按钮
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        LocalizedButton(btn_frame, text="选择当前目录", bg=COLOR_PRIMARY, fg="white",
                 font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12,
                 command=lambda: self._select_remote_path(path_var.get(), dialog)).pack(side=tk.RIGHT)
        LocalizedButton(btn_frame, text="取消", font=("Segoe UI", 9),
                 command=dialog.destroy).pack(side=tk.RIGHT, padx=8)

        self._list_remote_dir(listbox, path_var, dialog)

    def _list_remote_dir(self, listbox, path_var, dialog):
        """列出远程目录"""
        path = path_var.get().strip() or "/"
        dialog.title(f"浏览远程目录 - {path}")

        entries = self.ssh.list_dir(path)
        listbox.delete(0, tk.END)

        if path != "/":
            listbox.insert(tk.END, "../ (上级目录)")

        for entry in entries:
            if entry['type'] == 'dir':
                listbox.insert(tk.END, f"[DIR] {entry['name']}")
            else:
                size_mb = entry['size'] / 1024 / 1024
                if size_mb > 1024:
                    size_str = f"{size_mb/1024:.1f}GB"
                else:
                    size_str = f"{size_mb:.1f}MB"
                listbox.insert(tk.END, f"    {entry['name']}  ({size_str})")

    def _select_remote_path(self, path, dialog):
        """选择远程路径作为模型路径"""
        self.model_path_var.set(path)
        dialog.destroy()

    # ============================================================
    #  创建任务 - 分区3: 创建并执行任务(部署 → 配置 → 测试)
    # ============================================================

    def _build_task_run_section(self):
        frame = self.step_frames[1]

        self.run_section_header = self._build_section_header(
            frame, 3, "创建并执行任务",
            "一键完成: 部署容器 → 写入config.py → 执行测试 → 下载并解析结果; "
            "已有镜像直接复用, 代码导入容器后自动清理宿主机暂存目录")

        # 临时部署目录(仅部署过程暂存镜像tar/代码, 容器创建后自动删除)
        workdir_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        workdir_frame.pack(fill=tk.X, pady=(8, 4))

        LocalizedLabel(workdir_frame, text="临时部署目录:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.W, padx=16, pady=8)

        self.work_dir_var = tk.StringVar(value="/tmp/AISBench_Prefix_Tools")
        tk.Entry(workdir_frame, textvariable=self.work_dir_var, width=1,
               font=("Segoe UI", 9)).grid(row=0, column=1, sticky=tk.EW, padx=8, pady=8)
        workdir_frame.columnconfigure(1, weight=1)

        self.work_dir_status = LocalizedLabel(workdir_frame, text="", bg=COLOR_CARD,
                                        fg=COLOR_TEXT_MUTED, font=("Segoe UI", 9))
        self.work_dir_status.grid(row=0, column=2, padx=8, pady=8)

        # 检查目录 + 清理目录 按钮
        wd_btn_frame = tk.Frame(workdir_frame, bg=COLOR_CARD)
        wd_btn_frame.grid(row=0, column=3, padx=(0, 16), pady=8)
        LocalizedButton(wd_btn_frame, text="检查目录", font=("Segoe UI", 8),
                command=self._check_work_dir).pack(side=tk.LEFT, padx=2)
        self.clean_work_dir_btn = LocalizedButton(wd_btn_frame, text="清理目录", font=("Segoe UI", 8),
                bg=COLOR_ERROR, fg="white", relief=tk.FLAT,
                command=self._clean_work_dir, state=tk.DISABLED)
        self.clean_work_dir_btn.pack(side=tk.LEFT, padx=2)

        LocalizedLabel(workdir_frame,
                 text="仅部署期间暂存镜像tar/测试代码，代码导入容器后自动删除，不保留在宿主机",
                 bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8)
                 ).grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=16, pady=(0, 6))

        # 残留容器清理: 支持清理上次未清理的 aisbench-test-* 容器
        residual_frame = tk.Frame(workdir_frame, bg=COLOR_CARD)
        residual_frame.grid(row=2, column=0, columnspan=4, sticky=tk.W,
                            padx=16, pady=(0, 8))
        LocalizedButton(residual_frame, text="清理残留容器", font=("Segoe UI", 8),
                  bg=COLOR_ERROR, fg="white", relief=tk.FLAT,
                  command=self._open_residual_container_dialog
                  ).pack(side=tk.LEFT)
        self.residual_status_lbl = LocalizedLabel(residual_frame, text="未扫描",
                                             bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                             font=("Segoe UI", 8))
        self.residual_status_lbl.pack(side=tk.LEFT, padx=8)

        # 部署信息展示
        info_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        info_frame.pack(fill=tk.X, pady=4)

        self.docker_info_labels = {}
        info_items = [
            ("镜像:", "tar"),
            ("代码包:", "zip"),
            ("模型路径:", "model"),
            ("容器名称:", "container"),
            ("镜像名称:", "image"),
        ]
        for i, (label, key) in enumerate(info_items):
            LocalizedLabel(info_frame, text=label, bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                   font=("Segoe UI", 9)).grid(row=i, column=0, sticky=tk.W, padx=16, pady=4)
            val_lbl = LocalizedLabel(info_frame, text="-", bg=COLOR_CARD, fg=COLOR_TEXT,
                             font=("Segoe UI", 9))
            val_lbl.grid(row=i, column=1, sticky=tk.W, padx=16, pady=4)
            self.docker_info_labels[key] = val_lbl

        info_frame.columnconfigure(1, weight=1)

        # 任务执行按钮: 主按钮一键完成 部署→配置→执行; 辅助按钮支持仅部署
        btn_frame = tk.Frame(frame, bg=COLOR_BG)
        btn_frame.pack(fill=tk.X, pady=8)

        self.create_task_btn = LocalizedButton(
            btn_frame, text="🚀 创建任务", bg=COLOR_PRIMARY,
            fg="white", font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            command=self._create_task)
        self.create_task_btn.pack(side=tk.LEFT)

        self.deploy_btn = LocalizedButton(btn_frame, text="仅部署容器", bg=COLOR_BORDER,
                                    fg=COLOR_TEXT, font=("Segoe UI", 9),
                                    relief=tk.FLAT, padx=20, pady=6,
                                    command=self._start_deploy)
        self.deploy_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.cancel_deploy_btn = LocalizedButton(btn_frame, text="取消", bg=COLOR_ERROR,
                                           fg="white", font=("Segoe UI", 9),
                                           relief=tk.FLAT, padx=12, pady=6,
                                           command=self._cancel_deploy,
                                           state=tk.DISABLED)
        self.cancel_deploy_btn.pack(side=tk.LEFT, padx=8)

        # 日志输出
        LocalizedLabel(frame, text="部署日志:", bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(8, 4))

        self.docker_log = scrolledtext.ScrolledText(frame, height=14,
                                                    font=("Consolas", 9),
                                                    bg="#1e1e1e", fg="#d4d4d4",
                                                    insertbackground="white")
        self.docker_log.pack(fill=tk.BOTH, expand=True)

    def _log_docker(self, text):
        """向日志缓冲区写入（线程安全，由主线程定时刷新到UI）"""
        self._docker_log_handler.append(text)

    def _open_link(self, url: str):
        """在浏览器中打开下载链接"""
        try:
            webbrowser.open(url)
        except Exception as e:
            showerror("打开失败", trf("无法打开链接: {url}\n{error}", url=url, error=e))

    def _check_work_dir(self):
        """检查临时部署目录是否存在(旧版本/失败部署可能残留)"""
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return

        work_dir = self.work_dir_var.get().strip()
        if not work_dir:
            showwarning("提示", "请输入临时部署目录路径")
            return

        # 临时设置 remote_work_base 来检查
        if not self.docker:
            self.docker = DockerManager(self.ssh)
        self.docker.remote_work_base = work_dir

        if self.docker.work_dir_exists():
            # 目录已存在，检查内容
            code, out, _ = self.ssh.execute(f"ls -A {work_dir} 2>/dev/null")
            has_content = bool(out.strip())
            if has_content:
                self.work_dir_status.config(
                    text="⚠ 已存在且有内容", fg=COLOR_ERROR)
                self.clean_work_dir_btn.config(state=tk.NORMAL)
                choice = askyesnocancel(
                    "临时目录已存在",
                    trf("临时部署目录已存在且有内容:\n{work_dir}\n\n"
                        "目录内容:\n{content}\n\n"
                        "通常是上次部署失败或旧版本遗留的暂存文件。\n\n"
                        "是 - 删除残留暂存文件\n"
                        "否 - 忽略并继续部署(会覆盖同名文件)\n"
                        "取消 - 保持现状", work_dir=work_dir, content=out[:200]),
                    icon=messagebox.WARNING)
                if choice is True:
                    self._do_clean_work_dir()
                elif choice is None:
                    self.work_dir_status.config(text="保持现状", fg=COLOR_TEXT_MUTED)
            else:
                self.work_dir_status.config(text="已存在(空)", fg=COLOR_SUCCESS)
        else:
            self.work_dir_status.config(text="不存在(将创建)", fg=COLOR_SUCCESS)
            self.clean_work_dir_btn.config(state=tk.DISABLED)

    def _do_clean_work_dir(self):
        """执行清理临时部署目录"""
        work_dir = self.work_dir_var.get().strip()
        if not self.docker:
            self.docker = DockerManager(self.ssh)
        self.docker.remote_work_base = work_dir

        if not self.docker.work_dir_exists():
            self.work_dir_status.config(text="目录不存在，无需清理", fg=COLOR_TEXT_MUTED)
            return

        # 如果有容器在运行，先停止
        if self.docker.container_name and self.docker.container_is_running():
            self.docker.stop_and_remove()

        ok = self.docker.remove_work_dir()
        if ok:
            self.work_dir_status.config(text="已清理", fg=COLOR_SUCCESS)
            showinfo("成功", trf("已清理: {work_dir}", work_dir=work_dir))
        else:
            self.work_dir_status.config(text="清理失败", fg=COLOR_ERROR)
            showerror("失败", trf("清理失败: {work_dir}", work_dir=work_dir))

    def _clean_work_dir(self):
        """清理临时部署目录按钮回调"""
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return

        work_dir = self.work_dir_var.get().strip()
        if not askyesno("确认清理",
                                   trf("确定要清理临时部署目录吗?\n\n{work_dir}\n\n"
                                       "这将删除残留的暂存文件（镜像tar、代码包等），\n"
                                       "并停止当前会话创建的容器。\n"
                                       "容器内的测试代码和日志不受影响。", work_dir=work_dir),
                                   icon=messagebox.WARNING):
            return
        self._do_clean_work_dir()

    def _start_residual_scan(self, prompt_if_found: bool = False):
        """后台扫描执行机上本工具创建/遗留的容器"""
        if not self.ssh.connected:
            return
        if not self.docker:
            self.docker = DockerManager(self.ssh)

        def _do_scan():
            try:
                containers = self.docker.list_managed_containers(
                    include_test_state=True)
            except Exception:
                self.root.after(0, lambda: self.residual_status_lbl.config(
                    text="扫描失败(可稍后重试)", fg=COLOR_ERROR))
                return
            self.root.after(0, lambda: self._on_residual_scan_result(
                containers, prompt_if_found))

        self.residual_status_lbl.config(text="正在扫描残留容器...", fg=COLOR_TEXT_MUTED)
        threading.Thread(target=_do_scan, daemon=True).start()

    def _on_residual_scan_result(self, containers, prompt_if_found: bool):
        """展示残留容器扫描结果; 发现历史容器时提醒用户"""
        current = self.docker.container_name if self.docker else None
        residuals = [c for c in containers if c["name"] != current]
        if not containers:
            self.residual_status_lbl.config(text="无残留容器", fg=COLOR_SUCCESS)
            return

        suffix = " (含当前容器)" if current else ""
        self.residual_status_lbl.config(
            text=trf("发现 {count} 个本工具容器{suffix}",
                     count=len(containers), suffix=suffix),
            fg=COLOR_WARNING if residuals else COLOR_TEXT_MUTED)

        if prompt_if_found and residuals:
            listing = "\n".join(
                trf("  {name}  [{status}]  [{state}]",
                    name=c["name"], status=c["status"],
                    state=c.get("test_state_label", tr("未标记")))
                for c in residuals[:10])
            if len(residuals) > 10:
                listing += "\n  ..."
            if askyesno(
                    "发现残留容器",
                    trf("检测到 {count} 个本工具创建的历史容器:\n\n"
                        "{listing}\n\n"
                        "这些容器可能是上次退出时未清理的。\n"
                        "是否打开清理窗口进行选择清理?\n"
                        "(清理后如需再次执行测试, 需在\"创建任务\"中重新部署容器)",
                        count=len(residuals), listing=listing),
                    icon=messagebox.WARNING):
                self._open_residual_container_dialog()

    def _open_residual_container_dialog(self):
        """打开残留容器清理窗口(支持跨会话清理 aisbench-test-* 容器)"""
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return
        if not self.docker:
            self.docker = DockerManager(self.ssh)

        dialog = tk.Toplevel(self.root)
        dialog.title("清理残留容器")
        dialog.geometry("900x560")
        dialog.transient(self.root)
        dialog.configure(bg=COLOR_BG)

        LocalizedLabel(dialog, text="本工具创建的容器 (aisbench-test-*)",
                 bg=COLOR_BG, fg=COLOR_TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, padx=16, pady=(12, 4))
        LocalizedLabel(dialog,
                 text="点击行切换勾选，可清理上次退出时未删除的容器；仅显示本工具创建的容器",
                 bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 9)).pack(anchor=tk.W, padx=16)

        list_frame = tk.Frame(dialog, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        columns = ("name", "image", "status", "test_state", "created")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        for col, (text, width) in {
            "name": (tr("容器名"), 200),
            "image": (tr("镜像"), 240),
            "status": (tr("状态"), 130),
            "test_state": (tr("测试状态"), 130),
            "created": (tr("创建时间"), 120),
        }.items():
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor=tk.W)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.tag_configure("checked", background="#dcfce7")

        checked = set()

        def _toggle_row(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            name = tree.set(item, "name")
            if name in checked:
                checked.discard(name)
                tree.item(item, tags=())
            else:
                checked.add(name)
                tree.item(item, tags=("checked",))

        tree.bind("<ButtonRelease-1>", _toggle_row)

        option_frame = tk.Frame(dialog, bg=COLOR_BG)
        option_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        clean_temp_var = tk.BooleanVar(value=True)
        LocalizedCheckbutton(option_frame, text="同时删除临时部署目录残留文件",
                       variable=clean_temp_var, bg=COLOR_BG,
                       font=("Segoe UI", 9)).pack(side=tk.LEFT)
        status_lbl = LocalizedLabel(option_frame, text="", bg=COLOR_BG,
                              fg=COLOR_TEXT_MUTED, font=("Segoe UI", 9))
        status_lbl.pack(side=tk.LEFT, padx=12)

        log_box = scrolledtext.ScrolledText(dialog, height=8,
                                            font=("Consolas", 9),
                                            bg="#1e1e1e", fg="#d4d4d4")
        log_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        def _log(text):
            log_box.insert(tk.END, text)
            log_box.see(tk.END)

        def _log_async(text):
            dialog.after(0, lambda t=text: _log(t))

        def _refresh_list():
            status_lbl.config(text="正在刷新...", fg=COLOR_TEXT_MUTED)

            def _do_refresh():
                try:
                    containers = self.docker.list_managed_containers(
                        include_test_state=True)
                except Exception as e:
                    dialog.after(0, lambda: status_lbl.config(
                        text=trf("查询失败: {error}", error=e), fg=COLOR_ERROR))
                    return

                def _fill():
                    tree.delete(*tree.get_children())
                    checked.clear()
                    for c in containers:
                        tree.insert("", tk.END, values=(
                            c["name"], c["image"], c["status"],
                            c.get("test_state_label", tr("未标记")),
                            c["created"]))
                    count = len(containers)
                    status_lbl.config(
                        text=trf("共 {count} 个容器", count=count) if count else "无残留容器",
                        fg=COLOR_WARNING if count else COLOR_SUCCESS)
                    self.residual_status_lbl.config(
                        text=trf("发现 {count} 个本工具容器", count=count) if count else "无残留容器",
                        fg=COLOR_WARNING if count else COLOR_SUCCESS)

                dialog.after(0, _fill)

            threading.Thread(target=_do_refresh, daemon=True).start()

        def _select_all():
            for item in tree.get_children():
                checked.add(tree.set(item, "name"))
                tree.item(item, tags=("checked",))

        def _select_none():
            checked.clear()
            for item in tree.get_children():
                tree.item(item, tags=())

        def _clean_selected():
            if not checked:
                showwarning("提示", "请先点击列表行勾选要清理的容器",
                                       parent=dialog)
                return
            names = sorted(checked)
            state_by_name = {
                tree.set(item, "name"): tree.set(item, "test_state")
                for item in tree.get_children()
            }
            confirm_msg = (tr("确定停止并删除以下容器?\n\n")
                           + "\n".join(
                               trf("  {name}  [{state}]", name=n,
                                   state=state_by_name.get(n, tr("未标记")))
                               for n in names)
                           + tr("\n\n清理后如需再次执行测试, 需在\"创建任务\"中重新部署容器。"))
            if clean_temp_var.get():
                confirm_msg += trf("\n\n同时删除临时部署目录:\n  {work_dir}",
                                   work_dir=self.work_dir_var.get().strip())
            if not askyesno("确认清理", confirm_msg,
                                       icon=messagebox.WARNING, parent=dialog):
                return

            clean_btn.config(state=tk.DISABLED, text="清理中...")
            status_lbl.config(text="清理中...", fg=COLOR_TEXT_MUTED)

            def _do_clean():
                for name in names:
                    _log(trf("停止并删除容器: {name}\n", name=name))
                    self.docker.remove_container(name, callback=_log_async)
                    if self.docker.container_name == name:
                        self.docker.container_name = None
                        self.config_mgr = None
                        self.deployed = False
                    checked.discard(name)
                if clean_temp_var.get():
                    work_dir = self.work_dir_var.get().strip()
                    if work_dir:
                        self.docker.remote_work_base = work_dir
                    self.docker.remove_work_dir(callback=_log_async)
                _log("✓ 清理完成\n")
                _log(tr("如需再次执行测试用例, 请重新创建任务（重新部署容器）。\n"))

                def _done():
                    clean_btn.config(state=tk.NORMAL, text="清理选中")
                    self.work_dir_status.config(
                        text="临时目录已清理" if clean_temp_var.get() else "",
                        fg=COLOR_SUCCESS if clean_temp_var.get() else COLOR_TEXT_MUTED)
                    _refresh_list()

                dialog.after(0, _done)

            threading.Thread(target=_do_clean, daemon=True).start()

        action_frame = tk.Frame(dialog, bg=COLOR_BG)
        action_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        LocalizedButton(action_frame, text="刷新", command=_refresh_list,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        LocalizedButton(action_frame, text="全选", command=_select_all,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=6)
        LocalizedButton(action_frame, text="取消全选", command=_select_none,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        clean_btn = LocalizedButton(action_frame, text="清理选中", bg=COLOR_ERROR,
                              fg="white", font=("Segoe UI", 9, "bold"),
                              relief=tk.FLAT, command=_clean_selected)
        clean_btn.pack(side=tk.LEFT, padx=12)
        LocalizedButton(action_frame, text="关闭", command=dialog.destroy,
                  font=("Segoe UI", 9)).pack(side=tk.RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        _refresh_list()

    def _flush_log_buffer(self):
        """主线程定时刷新部署日志缓冲区到UI（每200ms）"""
        self._docker_log_handler.flush()
        self._flush_timer_id = self.root.after(200, self._flush_log_buffer)

    def _flush_exec_log_buffer(self):
        """主线程定时刷新执行日志缓冲区到UI（每200ms）"""
        self._exec_log_handler.flush()
        self._exec_flush_timer_id = self.root.after(200, self._flush_exec_log_buffer)

    def _cancel_deploy(self):
        """取消部署"""
        self._cancel_flag.set()
        self._log_docker(tr("\n⚠ 正在取消部署...\n"))

    def _collect_task_inputs(self) -> Optional[dict]:
        """校验并收集创建任务所需的资源输入(镜像/代码/模型/临时目录)

        返回None表示校验未通过; 通过则返回任务输入字典。
        供"仅部署容器"与"创建任务"共用。
        """
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return None

        image_mode = self.image_source_var.get()
        selected_image = self.remote_image_var.get().strip()
        tar = self.tar_path.get().strip()
        model = self.model_path_var.get().strip()
        work_dir = self.work_dir_var.get().strip()

        if self.code_source_var.get() == "builtin":
            code_dir = self._get_bundled_code_dir()
            if not os.path.isdir(code_dir):
                showerror("错误", trf(
                    "未找到内置测试代码目录:\n{code_dir}\n\n请改用本地zip包模式",
                    code_dir=code_dir))
                return None
        else:
            zipf = self.zip_path.get().strip()
            if not zipf:
                showwarning("提示", "请选择本地代码zip包 (或改用程序内置)")
                return None
            if not os.path.isfile(zipf):
                showwarning("提示", trf("zip包不存在: {path}", path=zipf))
                return None

        if image_mode == "existing":
            if not selected_image:
                showwarning("提示", "请先查看并选择执行机上的镜像")
                return None
        else:
            if not tar:
                showwarning("提示", "请选择要上传的AISBench镜像tar包")
                return None
            if not os.path.isfile(tar):
                showwarning("提示", trf("镜像tar包不存在: {path}", path=tar))
                return None

        if not model:
            showwarning("提示", "请先完成模型路径选择")
            return None
        if not work_dir:
            showwarning("提示", "请输入临时部署目录路径")
            return None

        # 部署前检查临时目录(仅用于暂存镜像tar/代码)
        # 复用已有DockerManager, 避免丢失当前会话容器引用(无法复用/清理)
        if not self.docker:
            self.docker = DockerManager(self.ssh)
        self.docker.remote_work_base = work_dir
        if self.docker.work_dir_exists():
            code, out, _ = self.ssh.execute(f"ls -A {work_dir} 2>/dev/null")
            if out.strip():
                choice = askyesnocancel(
                    "临时目录已存在",
                    trf("临时部署目录已存在且有内容:\n{work_dir}\n\n"
                        "通常是上次部署中断或旧版本遗留的暂存文件。\n\n"
                        "是 - 删除残留后继续部署\n"
                        "否 - 忽略并继续部署（覆盖同名文件）\n"
                        "取消 - 终止部署", work_dir=work_dir),
                    icon=messagebox.WARNING)
                if choice is True:
                    self.docker.remove_work_dir()
                elif choice is None:
                    return None
                # choice is False: 直接部署

        return {
            "image_mode": image_mode,
            "selected_image": selected_image,
            "tar": tar,
            "model": model,
            "work_dir": work_dir,
        }

    def _start_deploy(self):
        """仅部署容器(不执行测试); 完整任务请使用"创建任务"按钮"""
        inputs = self._collect_task_inputs()
        if inputs is None:
            return

        self._cancel_flag.clear()
        self._docker_log_handler.reset()
        self.docker_log.delete(1.0, tk.END)
        self.create_task_btn.config(state=tk.DISABLED)
        self.deploy_btn.config(state=tk.DISABLED, text="部署中...")
        self.cancel_deploy_btn.config(state=tk.NORMAL)
        self.clean_work_dir_btn.config(state=tk.DISABLED)

        # 启动定时刷新日志
        if self._flush_timer_id:
            self.root.after_cancel(self._flush_timer_id)
        self._flush_timer_id = self.root.after(200, self._flush_log_buffer)

        def _do_deploy():
            self._deploy_sequence(
                inputs["model"],
                inputs["tar"] if inputs["image_mode"] == "upload" else "",
                inputs["selected_image"] if inputs["image_mode"] == "existing" else "",
            )
            # 结束后恢复UI
            def _restore():
                self.create_task_btn.config(state=tk.NORMAL)
                self.deploy_btn.config(state=tk.NORMAL, text="重新部署")
                self.cancel_deploy_btn.config(state=tk.DISABLED)
                self.clean_work_dir_btn.config(state=tk.NORMAL)
                # 最后刷新一次确保所有日志已输出
                self._docker_log_handler.finalize()
                # 停止定时刷新
                if self._flush_timer_id:
                    self.root.after_cancel(self._flush_timer_id)
                    self._flush_timer_id = None
            self.root.after(0, _restore)

        threading.Thread(target=_do_deploy, daemon=True).start()

    def _container_reusable(self, model_path: str) -> bool:
        """判断当前会话容器能否复用(跳过部署直接执行测试)"""
        if not (self.deployed and self.docker and self.docker.container_name):
            return False
        if not self.docker.container_is_running():
            return False
        if self.deployed_model_path and self.deployed_model_path != model_path:
            return False
        selected = self.remote_image_var.get().strip()
        if (selected and self.deployed_image
                and selected != self.deployed_image):
            return False
        return True

    def _create_task(self):
        """一键创建任务: 部署容器 → 自动写入config.py → 执行测试 → 下载并解析结果"""
        inputs = self._collect_task_inputs()
        if inputs is None:
            return

        if not self.designer.test_cases:
            showwarning("提示", tr("请先生成测试用例"))
            return

        local_dir = self.local_output_var.get().strip()
        if not local_dir:
            showwarning("提示", tr("请选择本地结果保存目录"))
            return

        # 执行前同步最新速率, 避免生成用例后又修改速率导致命令/脚本不一致
        if not self._sync_request_rate():
            showwarning(
                "提示",
                "请求发送速率输入无效, 请输入数字\n"
                "(支持小数如 0.3; 0 表示Burst模式)")
            return

        reuse = self._container_reusable(inputs["model"])

        self._cancel_flag.clear()
        self._docker_log_handler.reset()
        self._exec_log_handler.reset()
        if not reuse:
            self.docker_log.delete(1.0, tk.END)
        self.exec_log.delete(1.0, tk.END)
        self._clear_results_table()
        self.create_task_btn.config(state=tk.DISABLED, text="任务执行中...")
        self.deploy_btn.config(state=tk.DISABLED)
        self.exec_test_btn.config(state=tk.DISABLED)
        self.cancel_deploy_btn.config(state=tk.NORMAL)
        self.clean_work_dir_btn.config(state=tk.DISABLED)

        # 部署日志与执行日志同时刷新
        if self._flush_timer_id:
            self.root.after_cancel(self._flush_timer_id)
        self._flush_timer_id = self.root.after(200, self._flush_log_buffer)
        if self._exec_flush_timer_id:
            self.root.after_cancel(self._exec_flush_timer_id)
        self._exec_flush_timer_id = self.root.after(200, self._flush_exec_log_buffer)

        def _do_task():
            self._task_sequence(inputs, local_dir, reuse)

            def _restore():
                self.create_task_btn.config(state=tk.NORMAL, text="🚀 创建任务")
                self.deploy_btn.config(state=tk.NORMAL, text="重新部署")
                self.exec_test_btn.config(state=tk.NORMAL, text="执行测试 → 生成CSV")
                self.cancel_deploy_btn.config(state=tk.DISABLED)
                self.clean_work_dir_btn.config(state=tk.NORMAL)
                if self.docker and self.docker.container_name:
                    self.cleanup_btn.config(state=tk.NORMAL)
                self._docker_log_handler.finalize()
                self._exec_log_handler.finalize()
                if self._flush_timer_id:
                    self.root.after_cancel(self._flush_timer_id)
                    self._flush_timer_id = None
                if self._exec_flush_timer_id:
                    self.root.after_cancel(self._exec_flush_timer_id)
                    self._exec_flush_timer_id = None
                # 测试完成后提醒清理
                self.root.after(200, self._show_cleanup_reminder)
            self.root.after(0, _restore)

        threading.Thread(target=_do_task, daemon=True).start()

    def _task_sequence(self, inputs: dict, local_dir: str, reuse: bool):
        """创建任务的后台执行序列(部署 → 配置 → 测试)"""
        if reuse:
            self._log_exec(trf(
                "[任务] 复用已部署容器 {container}, 跳过部署直接执行测试\n",
                container=self.docker.container_name))
        else:
            ok = self._deploy_sequence(
                inputs["model"],
                inputs["tar"] if inputs["image_mode"] == "upload" else "",
                inputs["selected_image"] if inputs["image_mode"] == "existing" else "",
            )
            if not ok:
                return

        self._prepare_and_run_tests(local_dir)

    def _prepare_and_run_tests(self, local_dir: str):
        """执行测试前的自动配置写入 + 测试流水线(后台线程调用)"""
        if not self._write_config_automatically():
            return
        self._run_test_sequence(local_dir)

    def _deploy_sequence(self, model_path, tar_path, selected_image) -> bool:
        """部署序列(返回是否成功; 由仅部署/创建任务两种入口共用)"""
        # 重新部署时先清理本次会话创建的旧容器, 避免容器堆积
        if self.docker.container_name:
            self._log_docker(tr("[任务] 停止并删除本次会话的旧容器...\n"))
            self.docker.stop_and_remove(
                callback=lambda t: self._log_docker(t))
            self.deployed = False
            self.config_mgr = None

        # DockerManager已在_start_deploy中初始化，保持remote_work_base设置
        work_dir = self.work_dir_var.get().strip()
        if work_dir:
            self.docker.remote_work_base = work_dir

        # Step 1: 检查Docker
        self._log_docker(tr("[1/5] 检查Docker环境...\n"))
        ok, msg = self.docker.check_docker_installed()
        if not ok:
            self._log_docker(trf("  ✗ {message}\n", message=tr(msg)))
            return False
        self._log_docker(trf("  ✓ {message}\n\n", message=tr(msg)))

        if self._cancel_flag.is_set():
            self._log_docker(tr("  ⚹ 已取消\n"))
            return False

        # 确保临时部署目录存在（仅部署期间暂存镜像tar/代码）
        self.ssh.mkdir_p(self.docker.remote_work_base)

        # Step 2: 优先复用执行机已有镜像; 仅在上传模式下加载tar包
        self._log_docker(tr("[2/5] 准备AISBench镜像...\n"))
        if selected_image:
            self.root.after(0, lambda n=selected_image: self.docker_info_labels["tar"].config(text=n))
            if not self.docker.image_exists(selected_image):
                self._log_docker(trf("  ✗ 镜像不存在: {image}\n", image=selected_image))
                self._log_docker(tr("  → 请返回本步骤重新查看已有镜像，或改用上传模式\n"))
                return False

            image_name = selected_image
            self._log_docker(trf("  ✓ 复用执行机已有镜像: {image}\n", image=image_name))
            self._log_docker(tr("  → 跳过镜像上传和docker load\n\n"))
            self.docker.image_name = image_name
        else:
            tar_name = os.path.basename(tar_path)
            self.root.after(0, lambda n=tar_name: self.docker_info_labels["tar"].config(text=n))

            # 从本地tar包读取镜像名（不上传，直接读manifest.json）
            image_name = DockerManager.get_image_name_from_tar(tar_path)

            if image_name and self.docker.image_exists(image_name):
                # 镜像已存在，跳过上传和加载
                self._log_docker(trf("  ✓ 镜像已存在: {image}\n", image=image_name))
                self._log_docker(tr("  → 跳过上传和docker load\n\n"))
                self.docker.image_name = image_name
            else:
                # 镜像不存在，需要上传和加载
                if image_name:
                    self._log_docker(trf("  镜像 {image} 不存在，需要上传并加载\n", image=image_name))
                else:
                    self._log_docker(tr("  无法从tar包预读镜像名，将上传后由docker load识别\n"))

                tar_size = os.path.getsize(tar_path)
                self._log_docker(trf("  上传镜像tar包 ({size}MB)...\n", size=tar_size//1024//1024))
                self.remote_tar_path = f"{self.docker.remote_work_base}/{tar_name}"

                def _upload_progress(transferred, total):
                    pct = transferred * 100 // total if total > 0 else 0
                    self._log_docker(trf(
                        "\r  上传中: {transferred}MB / {total}MB ({percent}%)",
                        transferred=transferred//1024//1024,
                        total=total//1024//1024, percent=pct))

                ok = self.ssh.upload_file(tar_path, self.remote_tar_path, _upload_progress)
                self._log_docker("\n")
                if not ok:
                    self._log_docker(tr("  ✗ 镜像上传失败\n"))
                    return False
                self._log_docker(tr("  ✓ 镜像上传完成\n"))

                # Docker load
                self._log_docker(tr("  加载Docker镜像...\n"))
                ok, image_name = self.docker.load_image(
                    self.remote_tar_path,
                    callback=lambda t: self._log_docker(t)
                )
                if not ok:
                    self._log_docker(trf("  ✗ 镜像加载失败: {image}\n", image=image_name))
                    return False
                self._log_docker("\n")

        self.root.after(0, lambda n=image_name: self.docker_info_labels["image"].config(text=n))

        if self._cancel_flag.is_set():
            self._log_docker(tr("  ⚹ 已取消\n"))
            return False

        # Step 3: 暂存测试代码 (内置目录 / 本地zip包)
        if self.code_source_var.get() == "builtin":
            self._log_docker(tr("[3/5] 暂存内置测试代码...\n"))
            code_src_dir = self._get_bundled_code_dir()
            extracted_path = f"{self.docker.remote_work_base}/aisbench_auto_tools_prefix-main"

            ok, msg = self.docker.upload_directory(
                code_src_dir, extracted_path,
                callback=lambda t: self._log_docker(t)  # 直接写缓冲区
            )
            if not ok:
                self._log_docker(trf("  ✗ 代码上传失败: {message}\n", message=tr(msg)))
                return False
            self.root.after(0, lambda: self.docker_info_labels["zip"].config(text="内置代码包"))
        else:
            self._log_docker(tr("[3/5] 暂存并解压代码zip包...\n"))
            zipf = self.zip_path.get().strip()
            zip_name = os.path.basename(zipf)
            remote_zip = f"{self.docker.remote_work_base}/{zip_name}"

            ok = self.ssh.upload_file(zipf, remote_zip)
            if not ok:
                self._log_docker(tr("  ✗ 代码包上传失败\n"))
                return False

            ok, extracted_path = self.docker.extract_code_zip(
                remote_zip,
                self.docker.remote_work_base,
                callback=lambda t: self._log_docker(t)  # 直接写缓冲区
            )
            if not ok:
                self._log_docker(tr("  ✗ 代码解压失败\n"))
                return False
            self.root.after(0, lambda n=zip_name: self.docker_info_labels["zip"].config(text=n))

        self._log_docker(trf("  ✓ 代码暂存完成: {path}\n\n", path=extracted_path))

        if self._cancel_flag.is_set():
            self._log_docker(tr("  ⚹ 已取消\n"))
            return False

        # Step 4: 创建容器(仅挂载模型路径, 代码随后导入)
        self._log_docker(tr("[4/5] 创建并启动容器...\n"))
        container_name = self.docker.generate_container_name()
        ok, msg = self.docker.create_container(
            image_name, model_path, container_name,
            callback=lambda t: self._log_docker(t)  # 直接写缓冲区
        )
        if not ok:
            self._log_docker(trf("  ✗ {message}\n", message=tr(msg)))
            return False

        self.root.after(0, lambda n=container_name: self.docker_info_labels["container"].config(text=n))
        self.root.after(0, lambda m=model_path: self.docker_info_labels["model"].config(text=m))
        self._log_docker(trf("\n  ✓ 容器 {container} 已启动运行\n", container=container_name))

        # Step 5: 导入代码到容器并删除宿主机暂存目录
        self._log_docker(tr("[5/5] 导入测试代码到容器并清理暂存目录...\n"))
        ok, msg = self.docker.copy_code_into_container(
            extracted_path,
            callback=lambda t: self._log_docker(t)
        )
        if not ok:
            self._log_docker(trf("  ✗ {message}\n", message=tr(msg)))
            self._log_docker(tr("  → 暂存目录暂不删除，可用于排障；修复后可重新部署\n"))
            return False

        self._log_docker(trf("  清理宿主机临时目录: {path}\n", path=self.docker.remote_work_base))
        self.docker.remove_work_dir(callback=lambda t: self._log_docker(t))
        self.docker.code_host_path = ""
        self.root.after(0, lambda: self.work_dir_status.config(
            text="部署后已自动清理", fg=COLOR_SUCCESS))
        self._log_docker(trf(
            "  ✓ 部署完成! 代码工作区: {path} (容器内)\n",
            path=self.docker.code_mount_path))

        # 初始化ConfigManager
        self.config_mgr = ConfigManager(self.docker)
        self.deployed = True

        # 设置DATASET_PATH
        self.dataset_path_var.set(self.docker.code_mount_path)

        # 记录本次部署资源, 供"创建任务"判断能否复用容器
        self.deployed_model_path = model_path
        self.deployed_image = image_name

        return True

    @staticmethod
    def _parse_config_content(content: str) -> dict:
        """从config.py文本中解析键值对"""
        import re
        values = {}
        for match in re.finditer(r'^(\w+)\s*=\s*"([^"]*)"', content, re.MULTILINE):
            values[match.group(1)] = match.group(2)
        pod_match = re.search(r'^POD_INFO\s*=\s*(.+)$', content, re.MULTILINE)
        if pod_match:
            values['POD_INFO'] = pod_match.group(1).strip()
        return values

    def _build_config_dict(self) -> dict:
        """汇总任务资源配置(服务参数默认自动生成, 高级设置可覆盖)"""
        host_ip = self.host_ip_var.get().strip()
        if not host_ip and hasattr(self, "conn_vars"):
            host_ip = self.conn_vars["host"].get().strip()
        dataset_path = self.dataset_path_var.get().strip()
        if not dataset_path and self.docker:
            dataset_path = self.docker.code_mount_path
        return {
            'model_name': self.model_name_var.get().strip() or 'ds',
            'model_path': self.model_path_var.get().strip(),
            'host_ip': host_ip,
            'host_port': self.host_port_var.get().strip() or '8000',
            'api_key': self.api_key_var.get().strip(),
            'dataset_path': dataset_path,
            'work_path': '/benchmark',
            'default_perf': 'default_perf',
            'output_dir': './outputs/default',
            'pod_info': self.pod_info_var.get().strip(),
        }

    def _write_config_automatically(self) -> bool:
        """执行测试前自动生成config.py写入容器并回读验证(后台线程调用)

        原"配置文件"步骤合并进创建任务流程: 模型路径来自任务资源,
        服务参数默认自动生成, 无需用户手工填写与保存。
        """
        if not self.config_mgr:
            self._log_exec(tr("  ✗ 容器未部署, 无法写入config.py\n"))
            return False

        config = self._build_config_dict()
        errors = self.config_mgr.validate_config(config)
        if errors:
            self._log_exec(tr("  ✗ 配置校验失败:\n")
                           + "".join(f"    {e}\n" for e in errors))
            return False

        self._log_exec(tr("[配置] 自动写入config.py到容器...\n"))
        ok = self.config_mgr.write_config_to_container(config)
        if not ok:
            self._log_exec(tr("  ✗ config.py写入失败\n"))
            return False

        read_back = self.config_mgr.read_config_from_container()
        if read_back is None:
            self._log_exec(tr("  ⚠ config.py已写入, 但回读验证失败(不影响继续执行)\n"))
            return True

        saved_values = self._parse_config_content(read_back)
        key_fields = ['MODEL_PATH', 'MODEL_NAME', 'HOST_IP', 'HOST_PORT', 'DATASET_PATH']
        mismatches = []
        for field in key_fields:
            gui_val = str(config.get(field.lower(), ''))
            saved_val = saved_values.get(field, '')
            if gui_val and saved_val and gui_val != saved_val:
                mismatches.append(
                    trf("    {field}: 界面={gui}  容器={container}\n",
                        field=field, gui=gui_val, container=saved_val))

        if mismatches:
            self._log_exec(tr("  ✗ config.py写入后回读不一致:\n") + "".join(mismatches))
            return False

        container_path = f"{self.docker.code_mount_path}/config.py"
        self._log_exec(trf("  ✓ config.py已写入并验证一致: {path}\n", path=container_path))
        self._log_exec(trf("    MODEL_PATH={model_path}  MODEL_NAME={model_name}  "
                           "HOST={host_ip}:{host_port}\n",
                           model_path=config['model_path'],
                           model_name=config['model_name'],
                           host_ip=config['host_ip'],
                           host_port=config['host_port']))
        return True

    # ============================================================
    #  创建任务 - 分区2: 测试参数与用例设计
    # ============================================================

    def _build_task_testcases_section(self):
        frame = self.step_frames[1]

        self.testcases_section_header = self._build_section_header(
            frame, 2, "测试参数与用例设计",
            "填写KV cache信息并生成测试用例; 可从vLLM日志一键筛选获取参数")

        # 计算公式说明
        formula_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        formula_frame.pack(fill=tk.X, pady=8)

        LocalizedLabel(formula_frame, text="计算公式:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky=tk.W,
                                                   padx=16, pady=(8, 2))

        formulas = [
            "并发数 = floor( total_kv_cache / (input_len + output_len) )",
            "最小请求数 = floor(total_kv_cache / input_len / repeat_rate) + 1",
            "推荐请求数 = 最小请求数 × 2",
            "KV使用率 = 并发数 × (input_len + output_len) / total_kv_cache × 100%",
        ]
        for i, f in enumerate(formulas):
            LocalizedLabel(formula_frame, text=f"  {f}", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                   font=("Consolas", 8)).grid(row=i+1, column=0, sticky=tk.W,
                                               padx=16, pady=1)

        # KV Cache信息输入
        kv_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        kv_frame.pack(fill=tk.X, pady=4)

        kv_fields = [
            ("单个DP组KV cache (tokens):", "kv_cache_var"),
            ("DP组数:", "dp_var"),
            ("模型最大上下文 (tokens):", "max_req_len_var"),
            ("前缀命中率 (0-1):", "repeat_rate_var"),
            ("请求发送速率 (0=Burst):", "request_rate_var"),
        ]

        for i, (label, var_name) in enumerate(kv_fields):
            LocalizedLabel(kv_frame, text=label, bg=COLOR_CARD, fg=COLOR_TEXT,
                   font=("Segoe UI", 9)).grid(row=i, column=0, sticky=tk.W, padx=16, pady=6)
            entry = tk.Entry(kv_frame, textvariable=getattr(self, var_name), width=20,
                           font=("Segoe UI", 9))
            entry.grid(row=i, column=1, padx=16, pady=6, sticky=tk.W)

        # KV cache 查询方式提示 (命令可复制, 支持从远程/容器日志直接筛选)
        hint_row = len(kv_fields)
        LocalizedLabel(kv_frame, text="查询方式:", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
               font=("Segoe UI", 8)).grid(row=hint_row, column=0, sticky=tk.NW,
                                          padx=16, pady=(6, 0))
        hint_frame = tk.Frame(kv_frame, bg="#f0f5ff")
        hint_frame.grid(row=hint_row, column=1, padx=16, pady=(6, 8), sticky=tk.EW)

        cmd_row = tk.Frame(hint_frame, bg="#f0f5ff")
        cmd_row.pack(fill=tk.X)
        # width=1 + fill=X: 随窗口伸缩, 长命令在输入框内滚动, 不把按钮顶出窗口
        cmd_entry = tk.Entry(cmd_row, textvariable=self.kv_grep_cmd_var,
                             state="readonly", readonlybackground="#f0f5ff",
                             fg=COLOR_PRIMARY, font=("Consolas", 8), width=1)
        cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cmd_entry.bind("<Control-a>",
                       lambda e: (cmd_entry.select_range(0, tk.END), "break")[1])
        self.kv_copy_btn = LocalizedButton(cmd_row, text="复制", font=("Segoe UI", 8),
                                     relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white",
                                     padx=10, command=self._copy_kv_grep_command)
        self.kv_copy_btn.pack(side=tk.LEFT, padx=(6, 0))

        btn_row = tk.Frame(hint_frame, bg="#f0f5ff")
        btn_row.pack(fill=tk.X, pady=(4, 0))
        LocalizedButton(btn_row, text="从日志自动获取 / 查看日志", font=("Segoe UI", 8),
                  relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white", padx=10,
                  command=self._open_log_browser).pack(side=tk.LEFT)
        LocalizedLabel(btn_row, text="(选择服务器/容器日志, 筛选结果可一键填入)",
                 bg="#f0f5ff", fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=8)

        self.kv_hint_lbl = LocalizedLabel(
            hint_frame,
            text="KV cache size → 单个DP组KV cache (tokens);   Maximum concurrency → 模型最大上下文 (tokens)",
            bg="#f0f5ff", fg=COLOR_TEXT_MUTED, font=("Segoe UI", 7),
            anchor=tk.W, justify=tk.LEFT, wraplength=420)
        self.kv_hint_lbl.pack(fill=tk.X)

        # 长提示按容器实际宽度自动换行, 避免单行文本把按钮顶出窗口
        def _wrap_kv_hint(event):
            self.kv_hint_lbl.config(wraplength=max(240, event.width - 8))
        hint_frame.bind("<Configure>", _wrap_kv_hint)

        kv_frame.columnconfigure(1, weight=1)

        # 输入长度选择
        in_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        in_frame.pack(fill=tk.X, pady=4)
        LocalizedLabel(in_frame, text="输入长度 (需小于模型最大上下文):", bg=COLOR_CARD,
               fg=COLOR_TEXT, font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, padx=16, pady=(8, 4))

        in_checks_frame = tk.Frame(in_frame, bg=COLOR_CARD)
        in_checks_frame.pack(padx=16, pady=(0, 8), fill=tk.X)

        def _fmt_len(n):
            if n >= 1048576:
                return f"{n//1048576}M"
            elif n >= 1024:
                return f"{n//1024}K"
            return str(n)

        for length in TestDesigner.PRESET_INPUT_LENGTHS:
            var = tk.BooleanVar(value=False)
            self.input_length_vars[length] = var
            cb = LocalizedCheckbutton(in_checks_frame, text=_fmt_len(length), variable=var,
                              bg=COLOR_CARD, font=("Segoe UI", 9))
            cb.pack(side=tk.LEFT, padx=4)

        # 输出长度选择
        out_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        out_frame.pack(fill=tk.X, pady=4)
        LocalizedLabel(out_frame, text="输出长度:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, padx=16, pady=(8, 4))

        out_checks_frame = tk.Frame(out_frame, bg=COLOR_CARD)
        out_checks_frame.pack(padx=16, pady=(0, 8), fill=tk.X)
        for length in TestDesigner.PRESET_OUTPUT_LENGTHS:
            var = tk.BooleanVar(value=(length in [512, 1024]))
            self.output_length_vars[length] = var
            cb = LocalizedCheckbutton(out_checks_frame, text=_fmt_len(length), variable=var,
                              bg=COLOR_CARD, font=("Segoe UI", 9))
            cb.pack(side=tk.LEFT, padx=4)

        # 生成按钮
        gen_frame = tk.Frame(frame, bg=COLOR_BG)
        gen_frame.pack(fill=tk.X, pady=8)
        LocalizedButton(gen_frame, text="生成测试用例", bg=COLOR_PRIMARY, fg="white",
                font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=16, pady=4,
                command=self._generate_test_cases).pack(side=tk.LEFT)

        LocalizedButton(gen_frame, text="添加用例", font=("Segoe UI", 8),
                command=self._add_test_case).pack(side=tk.LEFT, padx=4)
        LocalizedButton(gen_frame, text="复制用例", font=("Segoe UI", 8),
                command=self._duplicate_test_case).pack(side=tk.LEFT, padx=4)
        LocalizedButton(gen_frame, text="删除用例", font=("Segoe UI", 8),
                command=self._delete_test_case).pack(side=tk.LEFT, padx=4)

        # 测试用例 + 计算明细 (拖拽分隔条调整两者占比, 各保留最小高度)
        self.cases_paned = tk.PanedWindow(frame, orient=tk.VERTICAL,
                                          sashrelief=tk.RAISED, sashwidth=6,
                                          bg=COLOR_BORDER)
        self.cases_paned.pack(fill=tk.BOTH, expand=True, pady=(8, 4))

        # Pane 1: 测试用例表格
        tree_pane = tk.Frame(self.cases_paned, bg=COLOR_BG)
        self.cases_paned.add(tree_pane, minsize=160, stretch="always")
        LocalizedLabel(tree_pane, text="测试用例 (双击单元格可编辑 Input/Output/请求数/前缀数量/并发数):",
               bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 4))

        tree_frame = tk.Frame(tree_pane)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("num", "input", "output", "data_rec", "prefix_num",
                   "data_min", "concurrency", "kv_usage")
        self.test_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=4,
                                      selectmode="browse")

        headings = [("#", 40), (tr("Input"), 80), (tr("Output"), 80),
                    (tr("请求数(推荐)"), 120), (tr("前缀数量(prefix_num)"), 130),
                    (tr("请求数(最小)"), 120), (tr("并发数"), 80),
                    (tr("KV使用率"), 80)]
        for col, (title, width) in zip(columns, headings):
            self.test_tree.heading(col, text=title)
            self.test_tree.column(col, width=width, anchor=tk.CENTER)

        self.test_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.test_tree.yview).pack(
            side=tk.RIGHT, fill=tk.Y)

        self.test_tree.bind("<Double-1>", self._on_tree_edit)

        # Pane 2: 计算明细 (代入值展示)
        calc_pane = tk.Frame(self.cases_paned, bg=COLOR_BG)
        self.cases_paned.add(calc_pane, minsize=120, stretch="always")
        LocalizedLabel(calc_pane, text="计算明细 (代入当前KV参数):",
               bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 0))

        self.calc_detail_text = scrolledtext.ScrolledText(calc_pane, height=4,
                                                           font=("Consolas", 8),
                                                           bg="#f0f5ff", fg="#1e293b",
                                                           wrap=tk.WORD)
        self.calc_detail_text.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.calc_detail_text.insert(
            "1.0", tr("(点击\"生成测试用例\"后显示详细计算过程)"))

    def _show_calc_details(self):
        """显示代入值计算公式"""
        if not hasattr(self, 'calc_detail_text') or not self.designer.test_cases:
            return
        self.calc_detail_text.delete("1.0", tk.END)
        kv = self.designer.total_kv_cache
        rate = self.designer.repeat_rate
        dp = self.designer.dp
        lines = []
        for i, case in enumerate(self.designer.test_cases, 1):
            total = case.input_len + case.output_len
            max_cc_raw = kv / total
            min_req_raw = kv / case.input_len / rate + 1
            min_req = int(min_req_raw)
            rec_req = min_req * 2
            kv_usage = case.concurrency_recommended * total / kv * 100
            lines.append(trf(
                "用例 {index}  input={input:,}  output={output:,}  dp={dp}  repeat_rate={rate}%",
                index=i, input=case.input_len, output=case.output_len, dp=dp,
                rate=rate * 100))
            lines.append(trf(
                "  并发数(公式) = floor({kv:,} / ({input:,}+{output:,}))",
                kv=kv, input=case.input_len, output=case.output_len))
            lines.append(trf(
                "              = floor({raw:.2f}) = {value:,}",
                raw=max_cc_raw, value=case.concurrency_max))
            if case.concurrency_recommended != case.concurrency_max:
                lines.append(trf(
                    "  并发数(实际) = {value:,}  (用户手动调整)",
                    value=case.concurrency_recommended))
            lines.append(trf(
                "  最小请求数 = floor({kv:,} / {input:,} / {rate}) + 1",
                kv=kv, input=case.input_len, rate=rate))
            lines.append(f"            = floor({min_req_raw:.2f}) = {min_req}")
            lines.append(trf(
                "  推荐请求数 = {minimum:,} × 2 = {recommended:,}  (实际: {actual:,})",
                minimum=min_req, recommended=rec_req,
                actual=case.data_num_recommended))
            lines.append(trf(
                "  KV使用率  = {concurrency} × {total:,} / {kv:,} × 100% = {usage:.2f}%",
                concurrency=case.concurrency_recommended, total=total, kv=kv,
                usage=kv_usage))
            lines.append("")
        self.calc_detail_text.insert("1.0", "\n".join(lines).rstrip())

    def _copy_kv_grep_command(self):
        """复制KV cache查询命令到剪贴板"""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.kv_grep_cmd_var.get())
        self.root.update_idletasks()
        self.kv_copy_btn.config(text="已复制")
        self.root.after(1500, lambda: self.kv_copy_btn.config(text="复制"))

    def _open_log_browser(self):
        """打开远程日志工具: 选择服务器/容器日志文件, 筛选KV cache或查看日志"""
        RemoteLogBrowser(self.root, self.ssh,
                         kv_cache_var=self.kv_cache_var,
                         max_req_len_var=self.max_req_len_var,
                         on_command=self.kv_grep_cmd_var.set)

    def _generate_test_cases(self):
        """生成测试用例"""
        try:
            kv = int(self.kv_cache_var.get())
            dp = int(self.dp_var.get())
            max_len = int(self.max_req_len_var.get())
            rate = float(self.repeat_rate_var.get())
            req_rate = float(self.request_rate_var.get())
        except ValueError:
            showwarning(
                "提示",
                "请输入有效的数字\n"
                "(请求发送速率支持小数, 如 0.3 表示 0.3 req/s; 0 表示Burst模式)")
            return

        self.designer.set_kv_cache_info(kv, dp, max_len)
        self.designer.set_repeat_rate(rate)
        self.designer.set_request_rate(req_rate)

        # 获取选中的输入/输出长度
        in_lengths = [l for l, v in self.input_length_vars.items() if v.get()]
        out_lengths = [l for l, v in self.output_length_vars.items() if v.get()]

        if not in_lengths:
            valid = self.designer.get_valid_preset_inputs()
            if valid:
                in_lengths = valid[:2]
            else:
                showwarning("提示", "没有有效的输入长度")
                return

        if not out_lengths:
            out_lengths = [512, 1024]

        max_len = self.designer.max_request_length
        valid_selected = [l for l in in_lengths if l < max_len]
        skipped_inputs = self.designer.set_input_lengths(in_lengths)
        self.designer.set_output_lengths(out_lengths)
        self.designer.generate_test_cases()

        # 超长输入不再静默替换, 明确提示用户
        if skipped_inputs:
            def _fmt_len(n):
                if n >= 1048576:
                    return f"{n//1048576}M"
                elif n >= 1024:
                    return f"{n//1024}K"
                return str(n)
            skipped_str = ", ".join(_fmt_len(l) for l in skipped_inputs)
            if valid_selected:
                kept_str = ", ".join(_fmt_len(l) for l in sorted(valid_selected))
                showwarning(
                    "输入长度超出限制",
                    trf("以下选中的输入长度超过模型最大上下文 ({max_len:,})，已跳过:\n"
                        "  {skipped}\n\n"
                        "实际生成用例使用的输入长度: {kept}",
                        max_len=max_len, skipped=skipped_str, kept=kept_str))
            else:
                fallback_str = ", ".join(_fmt_len(l) for l in self.designer.input_lengths)
                showwarning(
                    "输入长度超出限制",
                    trf("所选输入长度全部超过模型最大上下文 ({max_len:,}):\n"
                        "  {skipped}\n\n"
                        "已自动改用有效长度: {fallback}",
                        max_len=max_len, skipped=skipped_str, fallback=fallback_str))

        self._refresh_test_tree()

    def _refresh_test_tree(self):
        """刷新测试用例表格"""
        def _fmt(n):
            if n >= 1048576:
                return f"{n//1048576}M"
            elif n >= 1024:
                return f"{n//1024}K"
            return str(n)

        for item in self.test_tree.get_children():
            self.test_tree.delete(item)

        for i, case in enumerate(self.designer.test_cases, 1):
            kv_usage = self.designer.get_kv_usage(case)
            self.test_tree.insert("", tk.END, values=(
                i, _fmt(case.input_len), _fmt(case.output_len),
                f"{case.data_num_recommended:,}", f"{case.prefix_num:,}",
                f"{case.data_num_min:,}", f"{case.concurrency_recommended:,}",
                f"{kv_usage:.1f}%"
            ))
        self._show_calc_details()

    def _adjust_cases(self, factor, adjust_type):
        """调整测试用例参数"""
        if not self.designer.test_cases:
            return
        if adjust_type == 'data':
            self.designer.adjust_data_num(factor)
        else:
            self.designer.adjust_concurrency(factor)
        self._refresh_test_tree()

    def _on_tree_edit(self, event):
        """双击Treeview单元格进行行内编辑"""
        row_id = self.test_tree.identify_row(event.y)
        col_id = self.test_tree.identify_column(event.x)
        if not row_id:
            return

        EDITABLE = self.TEST_TREE_EDITABLE_FIELDS
        if col_id not in EDITABLE:
            return
        field = EDITABLE[col_id]

        item_index = self.test_tree.index(row_id)
        if item_index >= len(self.designer.test_cases):
            return
        case = self.designer.test_cases[item_index]
        current_val = getattr(case, field)

        bbox = self.test_tree.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, w, h = bbox

        entry = tk.Entry(self.test_tree, font=("Segoe UI", 9), justify=tk.CENTER)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, str(current_val))
        entry.select_range(0, tk.END)
        entry.focus_set()

        done = [False]

        def _confirm(event=None):
            if done[0]:
                return
            done[0] = True
            val = entry.get().strip()
            try:
                num_val = int(val)
                if num_val <= 0:
                    entry.destroy()
                    return
            except ValueError:
                entry.destroy()
                return

            self._apply_tree_edit(case, field, num_val)

            entry.destroy()
            self._refresh_test_tree()

        def _cancel(event=None):
            if done[0]:
                return
            done[0] = True
            entry.destroy()

        entry.bind('<Return>', _confirm)
        entry.bind('<Escape>', _cancel)
        entry.bind('<FocusOut>', _confirm)

    def _apply_tree_edit(self, case, field: str, num_val: int):
        """应用测试用例表格中的单格编辑结果"""
        if field == 'input_len':
            new_total = num_val + case.output_len
            if (self.designer.max_request_length > 0
                    and new_total > self.designer.max_request_length):
                showwarning("参数超出限制",
                            trf("输入+输出长度 ({input_len:,}+{output_len:,}={total:,}) "
                                "超过模型最大上下文 ({max_len:,})",
                                input_len=num_val, output_len=case.output_len,
                                total=new_total,
                                max_len=self.designer.max_request_length))
                return
            case.input_len = num_val
        elif field == 'output_len':
            new_total = case.input_len + num_val
            if (self.designer.max_request_length > 0
                    and new_total > self.designer.max_request_length):
                showwarning("参数超出限制",
                            trf("输入+输出长度 ({input_len:,}+{output_len:,}={total:,}) "
                                "超过模型最大上下文 ({max_len:,})",
                                input_len=case.input_len, output_len=num_val,
                                total=new_total,
                                max_len=self.designer.max_request_length))
                return
            case.output_len = num_val
        elif field == 'data_num_recommended':
            old_data_num = case.data_num_recommended
            case.data_num_recommended = num_val
            if case.prefix_num == old_data_num:
                # 前缀数量默认与请求数保持一致; 用户单独修改过则不覆盖。
                case.prefix_num = num_val
            if num_val < case.data_num_min:
                showwarning(
                    "请求数低于最小值",
                    trf("请求数 ({count:,}) 低于最小请求数 ({min_count:,})\n\n"
                        "低于该值时, 请求前缀总量不会超出HBM KV Cache容量, "
                        "不会在HBM之外的KV Cache缓存介质中命中。\n\n"
                        "如需覆盖HBM之外的缓存介质, 请将请求数提高至 {raise_to:,} 及以上。",
                        count=num_val, min_count=case.data_num_min,
                        raise_to=case.data_num_min))
        elif field == 'prefix_num':
            case.prefix_num = num_val
        elif field == 'concurrency_recommended':
            case.concurrency_recommended = num_val

    def _add_test_case(self):
        """添加自定义测试用例"""
        dialog = tk.Toplevel(self.root)
        dialog.title("添加测试用例")
        dialog.geometry("360x260")
        dialog.transient(self.root)
        dialog.grab_set()

        field_defs = [
            ("输入长度:", "input_len"),
            ("输出长度:", "output_len"),
            ("请求数 (留空=推荐):", "data_num"),
            ("前缀数量 (留空=与请求数一致):", "prefix_num"),
            ("并发数 (留空=推荐):", "concurrency"),
        ]
        entry_vars = {}
        for i, (label, key) in enumerate(field_defs):
            LocalizedLabel(dialog, text=label, font=("Segoe UI", 9)).grid(
                row=i, column=0, padx=16, pady=8, sticky=tk.W)
            var = tk.StringVar()
            ent = tk.Entry(dialog, textvariable=var, width=15, font=("Segoe UI", 9))
            ent.grid(row=i, column=1, padx=16, pady=8)
            entry_vars[key] = var

        def _confirm(event=None):
            try:
                il = int(entry_vars['input_len'].get())
                ol = int(entry_vars['output_len'].get())
            except ValueError:
                showwarning("提示", "请输入有效的输入/输出长度", parent=dialog)
                return

            data_num = None
            prefix_num = None
            concurrency = None
            try:
                if entry_vars['data_num'].get().strip():
                    data_num = int(entry_vars['data_num'].get())
                if entry_vars['prefix_num'].get().strip():
                    prefix_num = int(entry_vars['prefix_num'].get())
                if entry_vars['concurrency'].get().strip():
                    concurrency = int(entry_vars['concurrency'].get())
            except ValueError:
                showwarning("提示", "请求数、前缀数量和并发数必须为数字", parent=dialog)
                return

            try:
                self.designer.add_custom_case(il, ol, data_num, concurrency,
                                              prefix_num)
            except ValueError as e:
                showwarning("参数超出限制", str(e), parent=dialog)
                return
            new_case = self.designer.test_cases[-1]
            if new_case.data_num_recommended < new_case.data_num_min:
                showwarning(
                    "请求数低于最小值",
                    trf("请求数 ({count:,}) 低于最小请求数 ({min_count:,})\n\n"
                        "低于该值时, 请求前缀总量不会超出HBM KV Cache容量, "
                        "不会在HBM之外的KV Cache缓存介质中命中。\n\n"
                        "如需覆盖HBM之外的缓存介质, 请将请求数提高至 {raise_to:,} 及以上。",
                        count=new_case.data_num_recommended,
                        min_count=new_case.data_num_min,
                        raise_to=new_case.data_num_min),
                    parent=dialog)
            self._refresh_test_tree()
            dialog.destroy()

        btn_frame = tk.Frame(dialog)
        btn_frame.grid(row=len(field_defs), column=0, columnspan=2, pady=12)
        LocalizedButton(btn_frame, text="确认", bg=COLOR_PRIMARY, fg="white",
                 font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=16, pady=4,
                 command=_confirm).pack(side=tk.LEFT, padx=8)
        LocalizedButton(btn_frame, text="取消", font=("Segoe UI", 9),
                 command=dialog.destroy).pack(side=tk.LEFT, padx=8)

        dialog.bind('<Return>', lambda e: _confirm())

    def _duplicate_test_case(self):
        """复制选中的测试用例到列表末尾"""
        selection = self.test_tree.selection()
        if not selection:
            showwarning("提示", "请先选择要复制的用例行")
            return
        item_index = self.test_tree.index(selection[0])
        if self.designer.duplicate_case(item_index):
            self._refresh_test_tree()
            # 选中新追加的行, 便于直接双击编辑
            children = self.test_tree.get_children()
            if children:
                last = children[-1]
                self.test_tree.selection_set(last)
                self.test_tree.see(last)

    def _delete_test_case(self):
        """删除选中的测试用例"""
        selection = self.test_tree.selection()
        if not selection:
            showwarning("提示", "请先选择要删除的用例行")
            return
        if len(self.designer.test_cases) <= 1:
            showwarning("提示", "至少保留一个测试用例")
            return
        item_index = self.test_tree.index(selection[0])
        if self.designer.delete_case(item_index):
            self._refresh_test_tree()

    # ============================================================
    #  创建任务 - 分区3续: 任务执行与结果(可复用已部署容器重复执行)
    # ============================================================

    def _build_task_execute_section(self):
        frame = self.step_frames[1]

        self.execute_section_header = tk.Frame(frame, bg=COLOR_BG)
        self.execute_section_header.pack(fill=tk.X, pady=(14, 2))
        LocalizedLabel(self.execute_section_header, text="任务执行与结果",
                       bg=COLOR_BG, fg=COLOR_TEXT,
                       font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        LocalizedLabel(self.execute_section_header,
                       text="容器就绪后可单独重复执行测试; config.py会在每次执行前自动写入容器",
                       bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=("Segoe UI", 9)
                       ).pack(anchor=tk.W)

        # 摘要
        self.summary_text = LocalizedLabel(frame, text="", bg=COLOR_CARD, fg=COLOR_TEXT,
                                   font=("Segoe UI", 9), justify=tk.LEFT,
                                   relief=tk.SOLID, bd=1, anchor=tk.W, width=80, height=8)
        self.summary_text.pack(fill=tk.X, pady=8)

        # 底部固定: 执行按钮 + 输出目录
        btn_frame = tk.Frame(frame, bg=COLOR_BG)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=4)

        LocalizedButton(btn_frame, text="刷新命令", font=("Segoe UI", 9),
                 command=self._refresh_commands).pack(side=tk.LEFT)
        self.exec_test_btn = LocalizedButton(btn_frame, text="执行测试 → 生成CSV", bg=COLOR_PRIMARY, fg="white",
                 font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=16, pady=4,
                 command=self._execute_tests)
        self.exec_test_btn.pack(side=tk.LEFT, padx=8)

        self.cleanup_btn = LocalizedButton(btn_frame, text="清理环境", bg=COLOR_ERROR, fg="white",
                 font=("Segoe UI", 9), relief=tk.FLAT, padx=12, pady=4,
                 command=self._cleanup_environment, state=tk.DISABLED)
        self.cleanup_btn.pack(side=tk.LEFT, padx=8)

        out_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        out_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=8)

        LocalizedLabel(out_frame, text="本地结果保存目录:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=12, pady=8)

        self.local_output_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "aisbench_results")
        )
        tk.Entry(out_frame, textvariable=self.local_output_var, width=1,
                font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=8)
        LocalizedButton(out_frame, text="浏览...", font=("Segoe UI", 8),
                command=self._browse_local_output).pack(side=tk.LEFT, padx=(4, 12), pady=8)

        # 中部: 命令预览 + 执行日志 (拖拽分隔条调整占比, 各保留最小高度)
        self.exec_paned = tk.PanedWindow(frame, orient=tk.VERTICAL,
                                         sashrelief=tk.RAISED, sashwidth=6,
                                         bg=COLOR_BORDER)
        self.exec_paned.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # Pane 1: 命令预览
        cmd_pane = tk.Frame(self.exec_paned, bg=COLOR_BG)
        self.exec_paned.add(cmd_pane, minsize=100, stretch="always")
        LocalizedLabel(cmd_pane, text="生成的测试命令:", bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 4))
        self.commands_text = scrolledtext.ScrolledText(cmd_pane, height=3,
                                                       font=("Consolas", 9),
                                                       bg="#1e1e1e", fg="#d4d4d4")
        self.commands_text.pack(fill=tk.BOTH, expand=True)

        # Pane 2: 执行日志
        log_pane = tk.Frame(self.exec_paned, bg=COLOR_BG)
        self.exec_paned.add(log_pane, minsize=120, stretch="always")
        LocalizedLabel(log_pane, text="执行日志:", bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 0))
        self.exec_log = scrolledtext.ScrolledText(log_pane, height=4,
                                                  font=("Consolas", 9),
                                                  bg="#1e1e1e", fg="#d4d4d4")
        self.exec_log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # Pane 3: 结果摘要表 (测试完成后展示, 不仅仅打印到日志)
        res_pane = tk.Frame(self.exec_paned, bg=COLOR_BG)
        self.exec_paned.add(res_pane, minsize=90, stretch="always")
        res_header = tk.Frame(res_pane, bg=COLOR_BG)
        res_header.pack(fill=tk.X, pady=(4, 0))
        LocalizedLabel(res_header, text="结果摘要:", bg=COLOR_BG, fg=COLOR_TEXT,
               font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.results_info_lbl = LocalizedLabel(res_header, text="(测试完成后显示结果摘要)",
                                         bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
                                         font=("Segoe UI", 8))
        self.results_info_lbl.pack(side=tk.LEFT, padx=8)
        LocalizedButton(res_header, text="结果对比分析", font=("Segoe UI", 8),
                  relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white", padx=10,
                  command=self._open_result_compare).pack(side=tk.RIGHT)

        res_tree_frame = tk.Frame(res_pane)
        res_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        res_columns = ("input", "output", "req", "max_cc", "cc", "in_tput",
                       "out_tput", "ttft_avg", "tpot_avg", "qps", "hbm_hit", "ext_hit")
        self.results_tree = ttk.Treeview(res_tree_frame, columns=res_columns,
                                         show="headings", height=3,
                                         selectmode="browse")
        res_headings = [("Input", 64), ("Output", 64), ("Req", 60), ("Max_CC", 64),
                        ("CC", 60), ("In_Tput", 84), ("Out_Tput", 84),
                        ("TTFT_avg", 80), ("TPOT_avg", 80), ("QPS", 60),
                        ("HBM_Hit%", 76), ("Ext_Hit%", 76)]
        for col, (title, width) in zip(res_columns, res_headings):
            self.results_tree.heading(col, text=title)
            self.results_tree.column(col, width=width, anchor=tk.CENTER,
                                     stretch=True)

        res_vsb = tk.Scrollbar(res_tree_frame, orient=tk.VERTICAL,
                               command=self.results_tree.yview)
        res_hsb = tk.Scrollbar(res_tree_frame, orient=tk.HORIZONTAL,
                               command=self.results_tree.xview)
        self.results_tree.config(yscrollcommand=res_vsb.set,
                                 xscrollcommand=res_hsb.set)
        self.results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        res_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        res_hsb.pack(side=tk.BOTTOM, fill=tk.X)

    def _browse_local_output(self):
        path = filedialog.askdirectory(title=tr("选择本地结果保存目录"))
        if path:
            self.local_output_var.set(path)

    def _open_result_compare(self):
        """打开结果对比分析: 选择两个测试结果目录, 按输入规模匹配并对比指标"""
        ResultCompareDialog(self.root)

    def _sync_request_rate(self):
        """将界面上最新的请求发送速率同步到designer
        (生成用例后再修改速率也能生效; 无效输入时保持上次有效值)"""
        try:
            self.designer.set_request_rate(float(self.request_rate_var.get()))
            return True
        except ValueError:
            return False

    def _refresh_commands(self):
        """刷新命令和摘要"""
        self._sync_request_rate()
        commands = self.designer.generate_commands()
        self.commands_text.delete(1.0, tk.END)
        for i, cmd in enumerate(commands, 1):
            self.commands_text.insert(tk.END, f"# 测试 {i}\n{cmd}\n\n")

        summary = self.designer.get_summary()
        self.summary_text.config(text=summary)

    def _clear_results_table(self, msg="(测试完成后显示结果摘要)"):
        """清空界面上的结果摘要表"""
        if not hasattr(self, 'results_tree'):
            return
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.results_info_lbl.config(text=msg)

    def _show_results_table(self, results, csv_path, log_dir):
        """在界面结果摘要表格中展示解析结果 (主线程调用)"""
        if not hasattr(self, 'results_tree'):
            return

        def _fmt(v, decimals=2):
            if v is None or v == "":
                return "-"
            try:
                return f"{float(v):,.{decimals}f}"
            except (ValueError, TypeError):
                return str(v)

        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

        for row in results:
            self.results_tree.insert("", tk.END, values=(
                _fmt(row.get('input_len'), 0), _fmt(row.get('output_len'), 0),
                _fmt(row.get('total_req'), 0), _fmt(row.get('max_cc'), 0),
                _fmt(row.get('cc'), 0),
                _fmt(row.get('input_token_throughput')),
                _fmt(row.get('output_throughput')),
                _fmt(row.get('TTFT_avg')), _fmt(row.get('TPOT_avg')),
                _fmt(row.get('qps')),
                _fmt(row.get('hbm_hit_rate'), 1),
                _fmt(row.get('external_hit_rate'), 1),
            ))

        self.results_info_lbl.config(
            text=trf("共 {count} 条记录  |  CSV: {csv_path}  |  日志: {log_dir}",
                     count=len(results), csv_path=csv_path, log_dir=log_dir))

    def _execute_tests(self):
        """复用已部署容器执行测试: 自动写入config.py → 生成.sh → 运行 → 下载日志 → 解析CSV"""
        if not self.docker or not self.docker.container_is_running():
            showwarning("提示", tr("容器未运行，请先完成部署"))
            return

        if not self.designer.test_cases:
            showwarning("提示", tr("请先生成测试用例"))
            return

        local_dir = self.local_output_var.get().strip()
        if not local_dir:
            showwarning("提示", tr("请选择本地结果保存目录"))
            return

        # 执行前同步最新速率, 避免生成用例后又修改速率导致命令/脚本不一致
        if not self._sync_request_rate():
            showwarning(
                "提示",
                "请求发送速率输入无效, 请输入数字\n"
                "(支持小数如 0.3; 0 表示Burst模式)")
            return

        self.exec_log.delete(1.0, tk.END)
        self._exec_log_handler.reset()
        self._clear_results_table()
        self.create_task_btn.config(state=tk.DISABLED)
        self.deploy_btn.config(state=tk.DISABLED)
        self.exec_test_btn.config(state=tk.DISABLED, text="执行中...")

        # 启动定时刷新执行日志
        if self._exec_flush_timer_id:
            self.root.after_cancel(self._exec_flush_timer_id)
        self._exec_flush_timer_id = self.root.after(200, self._flush_exec_log_buffer)

        def _do_execute():
            self._prepare_and_run_tests(local_dir)
            def _restore():
                self.create_task_btn.config(state=tk.NORMAL)
                self.deploy_btn.config(state=tk.NORMAL, text="重新部署")
                self.exec_test_btn.config(state=tk.NORMAL, text="执行测试 → 生成CSV")
                # 启用清理按钮
                if self.docker and self.docker.container_name:
                    self.cleanup_btn.config(state=tk.NORMAL)
                # 最后刷新一次
                self._exec_log_handler.finalize()
                if self._exec_flush_timer_id:
                    self.root.after_cancel(self._exec_flush_timer_id)
                    self._exec_flush_timer_id = None
                # 测试完成后提醒清理
                self.root.after(200, self._show_cleanup_reminder)
            self.root.after(0, _restore)

        threading.Thread(target=_do_execute, daemon=True).start()

    def _check_model_path_in_container(self) -> Tuple[bool, str]:
        """在容器内检查MODEL_PATH是否有效（路径存在且含config.json）"""
        check_script = (
            'import config, os, sys\n'
            'p = config.MODEL_PATH\n'
            'if not os.path.isdir(p):\n'
            '    print(f"FAIL: MODEL_PATH不存在: {p}")\n'
            '    print("请检查: 1)模型路径是否正确 2)Docker是否正确挂载了模型权重")\n'
            '    sys.exit(1)\n'
            'if not os.path.isfile(os.path.join(p, "config.json")):\n'
            '    print(f"FAIL: {p}/config.json 不存在")\n'
            '    print("模型权重可能未正确部署，Docker挂载可能创建了空目录")\n'
            '    sys.exit(1)\n'
            'print(f"OK: MODEL_PATH={p}")\n'
        )
        check_container_path = f"{self.docker.code_mount_path}/_check_model_path.py"
        if not self.docker.write_file_in_container(check_container_path, check_script):
            return False, "无法写入预检查脚本到容器内部"

        cmd = (
            f"docker exec -w {self.docker.code_mount_path} {self.docker.container_name} "
            f"python3 _check_model_path.py"
        )
        code, out, err = self.ssh.execute(cmd)
        self.docker.remove_file_in_container(check_container_path)

        out = out.strip()
        if code == 0 and "OK:" in out:
            return True, out
        return False, out if out else (err.strip() if err else "未知错误")

    def _run_test_sequence(self, local_dir):
        """执行测试的4阶段流水线（在后台线程中运行）"""
        # ===== 阶段0: 预检查模型路径 =====
        self._log_exec("[0/4] 预检查: 验证容器内MODEL_PATH...\n")
        model_ok, model_msg = self._check_model_path_in_container()
        if not model_ok:
            self._log_exec(f"  ✗ {model_msg}\n")
            self._log_exec("  请修正MODEL_PATH后重新保存config.py到容器，再重试\n")
            return
        self._log_exec(f"  ✓ {model_msg}\n\n")

        # ===== 阶段1: 生成.sh脚本 =====
        self._log_exec("[1/4] 生成测试脚本...\n")
        script_content, log_dir_name = self.designer.generate_shell_script()
        self._log_exec(f"  日志目录名: {log_dir_name}\n")

        # ===== 阶段2: 写入并运行脚本(容器内部) =====
        self._log_exec("\n[2/4] 写入测试脚本到容器并执行...\n")
        container_script = self.docker.write_script(script_content, "run_tests.sh")
        if not container_script:
            self._log_exec("  ✗ 无法将测试脚本写入容器内部\n")
            self.docker.set_test_state(
                self.docker.TEST_STATE_ABNORMAL,
                callback=lambda t: self._log_exec(t))
            return
        self._log_exec(f"  脚本路径(容器内): {container_script}\n")
        self._log_exec("  开始执行测试 (这可能需要较长时间)...\n\n")

        # 写入测试任务状态标记: 执行中
        self.docker.set_test_state(
            self.docker.TEST_STATE_RUNNING,
            callback=lambda t: self._log_exec(t))

        exit_code = self.docker.run_script(
            "run_tests.sh",
            callback=lambda t: self._log_exec(t),  # 直接写缓冲区
            timeout=7200
        )

        if exit_code != 0:
            self.docker.set_test_state(
                self.docker.TEST_STATE_ABNORMAL,
                callback=lambda t: self._log_exec(t))
            self._log_exec(f"\n  ⚠ 部分测试失败 (exit_code={exit_code})，继续下载日志以便排查...\n")
        else:
            self.docker.set_test_state(
                self.docker.TEST_STATE_COMPLETED,
                callback=lambda t: self._log_exec(t))
            self._log_exec(f"\n  ✓ 测试脚本执行完成\n")

        # ===== 阶段3: 下载日志 =====
        self._log_exec("\n[3/4] 下载测试日志到本地...\n")

        container_log_dir = self.docker.find_latest_log_dir()
        if not container_log_dir:
            container_log_dir = f"{self.docker.code_mount_path}/{log_dir_name}"

        self._log_exec(f"  容器内日志目录: {container_log_dir}\n")

        local_log_dir = os.path.join(local_dir, log_dir_name)
        os.makedirs(local_log_dir, exist_ok=True)

        local_log_files = self.docker.download_logs(
            container_log_dir, local_log_dir,
            callback=lambda t: self._log_exec(t)  # 直接写缓冲区
        )

        # 下载 aisbench 在容器工作目录生成的附加文件到统一目录
        extra_files = self.docker.download_extra_files(
            ["aisbench_all.log", "aisbench_result.csv"], local_log_dir,
            callback=lambda t: self._log_exec(t)
        )
        if extra_files:
            self._log_exec(f"  ✓ 已下载附加文件: {', '.join(os.path.basename(p) for p in extra_files)}\n")

        if not local_log_files:
            self._log_exec("  ✗ 未下载到任何日志文件\n")
            return

        self._log_exec(f"  ✓ 已下载 {len(local_log_files)} 个日志文件到 {local_log_dir}\n")

        # ===== 阶段4: 解析日志生成CSV =====
        self._log_exec("\n[4/4] 解析日志生成CSV结果...\n")

        csv_path = os.path.join(local_log_dir, f"results_{log_dir_name}.csv")

        results = parse_log_directory(
            local_log_dir, csv_path,
            progress_callback=lambda msg, ok, row: self._log_exec(msg + "\n")
        )

        if results:
            self._log_exec(f"\n{'='*60}\n")
            self._log_exec(f"✓ 测试完成! 结果已保存\n")
            self._log_exec(f"  CSV文件: {csv_path}\n")
            self._log_exec(f"  日志目录: {local_log_dir}\n")
            self._log_exec(f"  共 {len(results)} 条记录\n")
            self._log_exec(f"{'='*60}\n\n")

            # 输出结果摘要表
            self._log_exec("结果摘要:\n")
            self._log_exec("-" * 125 + "\n")
            self._log_exec(f"{'Input':>8} {'Output':>8} {'Req':>6} {'Max_CC':>8} {'CC':>8} "
                          f"{'In_Tput':>10} {'Out_Tput':>10} {'TTFT_avg':>10} {'TPOT_avg':>10} "
                          f"{'QPS':>8} {'HBM_Hit%':>10} {'Ext_Hit%':>10}\n")
            self._log_exec("-" * 125 + "\n")
            for row in results:
                self._log_exec(
                    f"{row.get('input_len',''):>8} {row.get('output_len',''):>8} "
                    f"{str(row.get('total_req','')):>6} "
                    f"{str(row.get('max_cc','')):>8} {str(row.get('cc','')):>8} "
                    f"{str(row.get('input_token_throughput','')):>10} {str(row.get('output_throughput','')):>10} "
                    f"{str(row.get('TTFT_avg','')):>10} {str(row.get('TPOT_avg','')):>10} "
                    f"{str(row.get('qps','')):>8} {str(row.get('hbm_hit_rate','')):>10} "
                    f"{str(row.get('external_hit_rate','')):>10}\n"
                )
            self._log_exec("-" * 125 + "\n")

            # 将结果摘要以表格形式展示到界面上
            self.root.after(0, lambda: self._show_results_table(
                results, csv_path, local_log_dir))

            self.root.after(0, lambda: showinfo(
                "完成",
                trf("测试完成!\n\nCSV: {csv}\n日志: {log}\n共 {count} 条记录",
                    csv=csv_path, log=local_log_dir, count=len(results))
            ))
        else:
            self._log_exec("  ✗ 未能从日志中提取到有效结果\n")
            self.root.after(0, lambda: self._clear_results_table(
                "✗ 未提取到有效结果，请检查执行日志"))
            preflight_path = os.path.join(local_log_dir, "preflight.log")
            if os.path.exists(preflight_path):
                try:
                    with open(preflight_path, 'r', encoding='utf-8', errors='replace') as f:
                        preflight_content = f.read().strip()
                    if preflight_content:
                        self._log_exec(f"  预检查错误信息:\n{preflight_content}\n")
                except Exception:
                    pass
            else:
                test_logs = [f for f in os.listdir(local_log_dir) if f.endswith('.log')]
                if test_logs:
                    self._log_exec(f"  请检查以下日志文件中的错误信息:\n  {', '.join(test_logs)}\n")
                    self._log_exec(f"  日志目录: {local_log_dir}\n")
            self.root.after(0, lambda: showwarning("提示", "测试已完成但未提取到有效结果，请检查执行日志"))

    def _log_exec(self, text):
        """向执行日志缓冲区写入（线程安全，由主线程定时刷新）"""
        self._exec_log_handler.append(text)

    def _container_test_state_label(self) -> str:
        """读取当前容器内测试任务状态标记并转为本地化展示文本"""
        state = None
        running = None
        if self.docker and self.docker.container_name:
            try:
                state = self.docker.read_test_state()
            except Exception:
                state = None
            try:
                running = self.docker.container_is_running()
            except Exception:
                running = None
        if not isinstance(state, str):
            state = None
        return describe_test_state(state, running)

    def _show_cleanup_reminder(self):
        """测试完成后提醒清理远程环境"""
        if not self.docker or not self.docker.container_name:
            return

        work_dir = self.work_dir_var.get().strip()
        work_dir_line = (
            trf("  - 临时部署目录残留: {work_dir} (正常情况下已自动清理)\n", work_dir=work_dir)
            if work_dir else "")
        state_label = self._container_test_state_label()
        msg = trf(
            "测试已完成! 建议清理远程环境:\n\n"
            "  - Docker容器: {container}\n"
            "  - 测试任务状态: {state}\n"
            "{work_dir_line}"
            "\n是否立即清理?\n"
            "(是: 停止并删除容器 + 删除残留暂存文件, 本地结果不受影响)\n"
            '(否: 稍后可点击"清理环境"按钮手动清理)\n'
            "\n注意: 清理后容器将被删除, 如需再次执行测试用例,\n"
            "需要重新创建任务（重新部署容器）。",
            container=self.docker.container_name,
            state=state_label,
            work_dir_line=work_dir_line)

        if askyesno("清理提醒", msg, icon=messagebox.QUESTION):
            self._cleanup_environment()

    def _cleanup_environment(self, skip_confirm=False):
        """清理Docker容器和可能残留的临时部署目录"""
        if not self.docker:
            return

        work_dir = self.work_dir_var.get().strip()

        if not skip_confirm:
            container_line = (
                trf("  Docker容器: {container}\n", container=self.docker.container_name)
                if self.docker.container_name else "")
            state_line = (
                trf("  测试任务状态: {state}\n",
                    state=self._container_test_state_label())
                if self.docker.container_name else "")
            work_dir_line = (
                trf("  临时部署目录: {work_dir} (如有残留)\n", work_dir=work_dir)
                if work_dir else "")
            msg = trf(
                "确认清理以下远程资源?\n\n"
                "{container_line}"
                "{state_line}"
                "{work_dir_line}"
                "\n清理后容器将停止删除, 残留暂存文件将被清除。\n"
                "本地下载的测试结果不受影响。\n"
                "清理后如需再次执行测试用例, 请重新创建任务（重新部署容器）。\n",
                container_line=container_line,
                state_line=state_line,
                work_dir_line=work_dir_line)
            if not askyesno("确认清理", msg, icon=messagebox.WARNING):
                return

        self.cleanup_btn.config(state=tk.DISABLED, text="清理中...")

        def _do_cleanup():
            self._log_exec("\n===== 清理远程环境 =====\n")

            # 1. 停止并删除容器
            if self.docker.container_name:
                self._log_exec(f"  停止并删除容器: {self.docker.container_name}\n")
                self.docker.stop_and_remove(callback=lambda t: self._log_exec(t))
                self._log_exec("  ✓ 容器已清理\n")
                self.deployed = False
                self.config_mgr = None
            else:
                self._log_exec("  (无容器需要清理)\n")

            # 2. 清理可能残留的临时部署目录(部署成功时已自动删除)
            if work_dir:
                self.docker.remote_work_base = work_dir
                if self.docker.work_dir_exists():
                    self._log_exec(f"  清理临时部署目录: {work_dir}\n")
                    ok = self.docker.remove_work_dir(callback=lambda t: self._log_exec(t))
                    if ok:
                        self._log_exec("  ✓ 临时部署目录已清理\n")
                    else:
                        self._log_exec("  ✗ 临时部署目录清理失败\n")
                else:
                    self._log_exec("  (临时部署目录无残留)\n")

            # 3. 提示是否仍有历史容器残留(可在创建任务页清理)
            try:
                leftovers = [
                    c for c in self.docker.list_managed_containers(
                        include_test_state=True)
                    if c["name"] != self.docker.container_name
                ]
                if leftovers:
                    listing = ", ".join(
                        trf("{name}({state})", name=c["name"],
                            state=c.get("test_state_label", tr("未标记")))
                        for c in leftovers[:5])
                    self._log_exec(
                        trf("  ⚠ 仍有 {count} 个历史容器残留: {listing}\n",
                            count=len(leftovers), listing=listing))
                    self._log_exec("    → 可点击\"清理残留容器\"进行清理\n")
            except Exception:
                pass

            self._log_exec("\n✓ 环境清理完成!\n")
            local_dir = self.local_output_var.get().strip()
            self._log_exec(f"  本地测试结果保留在: {local_dir}\n")
            self._log_exec(tr(
                "  如需再次执行测试用例, 请重新创建任务（重新部署容器）。\n"))

            def _restore_cleanup():
                self.cleanup_btn.config(state=tk.DISABLED, text="清理环境")
                if getattr(self, '_exit_after_cleanup', False):
                    self.ssh.disconnect()
                    self.root.destroy()
                else:
                    showinfo("清理完成",
                        "环境清理完成!\n容器已删除, 临时目录无残留。\n本地测试结果不受影响。\n"
                        "如需再次执行测试用例, 请重新创建任务（重新部署容器）。")

            self.root.after(0, _restore_cleanup)

        threading.Thread(target=_do_cleanup, daemon=True).start()

    # ============================================================
    #  导航逻辑
    # ============================================================

    def _show_step(self, step):
        """显示指定步骤"""
        if step < 0 or step >= len(self.step_frames):
            return

        for i, frame in enumerate(self.step_frames):
            if i == step:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

        self.current_step = step

        # 切换步骤后重新同步内容区高度(等pack布局完成), 并回到顶部
        if hasattr(self, '_content_canvas'):
            self._content_canvas.yview_moveto(0)
            self._content_canvas.after_idle(self._apply_content_size)

        # 更新侧边栏
        for i, (indicator, label) in enumerate(self.step_buttons):
            if i == step:
                indicator.config(text="●", fg=COLOR_PRIMARY)
                label.config(fg=COLOR_PRIMARY, font=("Segoe UI", 10, "bold"))
            elif i < step:
                indicator.config(text="✓", fg=COLOR_SUCCESS)
                label.config(fg=COLOR_TEXT, font=("Segoe UI", 10))
            else:
                indicator.config(text="○", fg=COLOR_TEXT_MUTED)
                label.config(fg=COLOR_TEXT_MUTED, font=("Segoe UI", 10))

        # 更新按钮状态
        self.prev_btn.config(state=tk.NORMAL if step > 0 else tk.DISABLED)
        if step == len(self.step_frames) - 1:
            self.next_btn.config(text="完成", command=self._finish)
        else:
            self.next_btn.config(text="下一步 >", command=self._next_step)

        # 步骤特定的刷新
        if step == 1 and self.ssh.connected and not self.remote_images:
            self._refresh_remote_images()
            self._update_service_summary()
        if step == 1:
            self._refresh_commands()
            if hasattr(self, 'cleanup_btn') and self.docker and self.docker.container_name:
                self.cleanup_btn.config(state=tk.NORMAL)

    def _next_step(self):
        """下一步"""
        if self.current_step == 0 and not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return

        self._show_step(self.current_step + 1)

    def _prev_step(self):
        """上一步"""
        self._show_step(max(0, self.current_step - 1))

    def _exit_check_cleanup(self) -> bool:
        """退出前检查远程环境是否已清理
        返回True: 可立即退出; False: 用户取消或清理完成后自动退出"""
        if self.docker and self.docker.container_name and self.docker.container_is_running():
            work_dir = self.work_dir_var.get().strip()
            work_dir_line = (
                trf("  临时部署目录残留: {work_dir} (如有)\n", work_dir=work_dir)
                if work_dir else "")
            state_label = self._container_test_state_label()
            msg = trf(
                "检测到Docker容器仍在运行!\n\n"
                "  容器: {container}\n"
                "  测试任务状态: {state}\n"
                "{work_dir_line}"
                "\n退出前是否清理远程环境?\n"
                "(是: 清理后退出  否: 直接退出保留容器  取消: 不退出)\n"
                '(未清理的容器下次连接时可在"创建任务"页通过"清理残留容器"删除)\n'
                "\n注意: 清理后如需再次执行测试用例, 需重新创建任务（重新部署容器）;\n"
                "若测试任务正在执行中, 直接退出将导致测试异常终止。",
                container=self.docker.container_name,
                state=state_label,
                work_dir_line=work_dir_line)

            choice = askyesnocancel("清理提醒", msg, icon=messagebox.WARNING)
            if choice is None:
                return False  # 取消 - 不退出
            if choice:
                # 清理后退出
                self._exit_after_cleanup = True
                self._cleanup_environment(skip_confirm=True)
                return False
        return True

    def _finish(self):
        """完成"""
        if self._exit_check_cleanup() and \
                askyesno("完成", "测试已完成，是否退出程序?"):
            self.ssh.disconnect()
            self.root.destroy()

    def _on_close_window(self):
        """点击窗口×按钮: 环境未清理时提醒后再退出"""
        if self._exit_check_cleanup():
            self.ssh.disconnect()
            self.root.destroy()

    def run(self):
        """运行应用"""
        self.root.mainloop()


def main():
    app = WizardApp()
    app.run()


if __name__ == "__main__":
    main()
