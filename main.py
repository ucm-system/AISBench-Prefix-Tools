#!/usr/bin/env python3
"""
AISBenchPrefixTools - Windows GUI应用程序
用于远程部署和配置AISBench测试环境

功能流程:
  1. 连接远程执行机 (SSH)
  2. 创建任务: 配置镜像/代码/模型与服务参数, 设计用例, 确认后一键执行
  3. 任务列表: 查看多任务运行状态/全量日志/结果, 支持复制/取消/清理/删除
  (每任务独立SSH连接与容器; 本地日志文件与元数据持久化)
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
from docker_manager import DockerManager
from test_designer import TestDesigner
from log_tools import RemoteLogBrowser, KV_GREP_COMMAND
from result_compare import ResultCompareDialog
from task_manager import TaskInputs, TaskManager, TaskStatus
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


class WizardApp:
    """向导式GUI主程序"""

    APP_VERSION = "1.9.0"

    STEP_TITLES = [
        "SSH连接",
        "创建任务",
        "任务列表",
    ]

    # 任务列表页签始终可访问(不依赖当前步骤进度)
    TASKLIST_STEP = 2

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
        self.root.title(f"AISBenchPrefixTools v{self.APP_VERSION}")
        self.root.geometry("1180x780")
        self.root.minsize(960, 640)
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

        # 核心组件: 主SSH连接(表单/浏览用) + 多任务管理器(每任务独立SSH)
        self.ssh = SSHManager()
        # UI层Docker操作(镜像列表/残留容器清理); 任务执行使用各自的连接
        self.docker: Optional[DockerManager] = None
        self.designer = TestDesigner()
        self.task_manager = TaskManager()
        self.task_manager.on_change = self._on_task_manager_change

        # 用户偏好: 界面语言(中文/English)
        self.settings = load_settings()
        language_code = str(self.settings.get("language", "zh"))
        self.language_var = tk.StringVar(value=SUPPORTED_LANGUAGES.get(language_code, "中文"))
        set_language(language_code)

        # 导航状态
        self.current_step = 0

        # 任务资源表单
        self.remote_images = []
        self.remote_image_filter_var = tk.StringVar()
        self.image_source_var = tk.StringVar(value="existing")
        self.remote_image_var = tk.StringVar()
        self.task_name_var = tk.StringVar()
        self.tar_path = tk.StringVar()
        self.zip_path = tk.StringVar()
        self.code_source_var = tk.StringVar(value="builtin")
        self.model_path_var = tk.StringVar()
        self.work_dir_var = tk.StringVar(value="/tmp/AISBench_Prefix_Tools")

        # 服务配置(vLLM)
        self.host_ip_var = tk.StringVar()
        self.host_port_var = tk.StringVar(value="8000")
        self.model_name_var = tk.StringVar(value="ds")
        self.api_key_var = tk.StringVar()
        self.pod_info_var = tk.StringVar()

        # 测试用例相关变量
        self.kv_cache_var = tk.StringVar()
        self.dp_var = tk.StringVar(value="1")
        self.max_req_len_var = tk.StringVar()
        self.repeat_rate_var = tk.StringVar(value="0.9")
        self.request_rate_var = tk.StringVar(value="0")
        self.kv_grep_cmd_var = tk.StringVar(value=KV_GREP_COMMAND)
        self.input_length_vars = {}
        self.output_length_vars = {}
        self.local_output_var = tk.StringVar(value=os.path.join(
            os.path.expanduser("~"), "aisbench_results"))

        # 任务列表页状态
        self.selected_task_id = None
        self._task_poll_id = None
        self._task_log_pending_shown = False

        self._build_ui()
        self._schedule_task_poll()

    def _build_menubar(self):
        """菜单栏: 帮助(使用说明/关于)"""
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=tr("使用说明"), command=self._show_usage_help)
        help_menu.add_separator()
        help_menu.add_command(label=tr("关于 AISBench PrefixTools"),
                              command=self._show_about)
        menubar.add_cascade(label=tr("帮助"), menu=help_menu)
        self.root.config(menu=menubar)

    def _show_usage_help(self):
        """使用说明(纯文本, 首次使用用户可从菜单栏或F1打开)"""
        dlg = tk.Toplevel(self.root)
        dlg.title(tr("使用说明 - AISBench PrefixTools"))
        dlg.geometry("760x600")
        dlg.transient(self.root)

        text = scrolledtext.ScrolledText(
            dlg, wrap=tk.WORD, font=("Segoe UI", 10),
            bg="white", fg=COLOR_TEXT, relief=tk.FLAT,
            padx=16, pady=12)
        text.pack(fill=tk.BOTH, expand=True)

        quick = [
            tr("本工具将AISBench测试流程简化为两步操作:"),
            tr("  步骤 1  SSH连接: 填写执行机IP/端口/账号并测试连接。"),
            tr("  步骤 2  创建任务: 选择镜像、代码与模型路径, 设计测试用例,"),
            tr("            点击\"创建任务\"一键完成 部署容器 → 写入config.py →"),
            tr("            执行测试 → 下载并解析结果。"),
            tr("  任务列表: 查看每个任务的运行状态、执行日志与结果,"),
            tr("            支持复制新建、取消、清理与删除任务数据。"),
            tr("  结果对比分析: 无需连接服务器, 对比多次测试的CSV结果。"),
        ]
        conn = [
            tr("填写执行机IP、SSH端口、用户名, 以及密码或密钥。"),
            tr("点击\"测试连接\"验证。连接成功后会自动扫描上次退出"),
            tr("未清理的 aisbench-test-* 容器并提醒清理。"),
        ]
        task = [
            tr("任务资源: 选择AISBench镜像(优先复用执行机已有镜像, 支持关键字筛选),"),
            tr("  选择测试代码来源(程序内置或本地zip包), 指定模型权重路径,"),
            tr("  可选临时部署目录(默认 /tmp/AISBench_Prefix_Tools,"),
            tr("  每个任务会在其下自动创建独立子目录, 部署后自动删除)。"),
            tr("服务配置: vLLM服务连接参数, 默认自动生成(模型名ds、IP=执行机IP、"),
            tr("  端口8000), 特殊场景可修改; POD_INFO用于多DP场景。"),
            tr("测试参数: 填写单个DP组KV cache、DP数、模型最大上下文等;"),
            tr("  可点击\"从日志自动获取\"打开远程日志工具一键筛选填入;"),
            tr("  勾选输入/输出长度后生成测试用例, 用例表格支持双击编辑。"),
            tr("创建任务: 点击\"创建任务\"前会弹出全量信息确认对话框;"),
            tr("  也可点击\"预览任务信息\"随时查看当前表单汇总(未创建亦可预览)。"),
            tr("任务名称: 留空时自动使用 服务名_时间(如 ds_20261102_153000)。"),
        ]
        tasklist = [
            tr("创建任务后自动跳转到任务列表, 实时查看运行状态与全量日志。"),
            tr("  复制新建: 将已有任务的配置预填到创建任务表单。"),
            tr("  取消任务: 终止运行中的任务(执行阶段会停止容器以中断测试)。"),
            tr("  清理资源: 删除任务的容器与远程暂存目录(需已连接执行机)。"),
            tr("  删除数据: 删除任务记录及其本地日志/结果文件, 释放磁盘空间。"),
            tr("  全屏日志: 将执行日志放大到独立窗口查看。"),
            tr("每个任务的日志同时写入本地文件(工具数据目录 logs/ 下, 每任务一个)。"),
        ]
        compare = [
            tr("独立工具, 无需连接服务器。选择两个 results_*.csv 文件,"),
            tr("  按Input/Output/请求数等维度生成差异对比表, 支持导出CSV与图片,"),
            tr("  数据标签可自定义(默认取文件名)。"),
        ]
        faq = [
            tr("Q: 部署日志提示镜像不存在?"),
            tr("A: 返回创建任务页重新\"查看已有镜像\", 或改用上传tar包模式。"),
            "",
            tr("Q: 测试完成后如何再次执行?"),
            tr("A: 修改用例后在创建任务页重新创建任务, 或在任务列表复制新建。"),
            "",
            tr("Q: Windows提示\"已阻止启动无法识别的应用\"?"),
            tr("A: 未签名EXE的SmartScreen提示, 点击\"更多信息\"→\"仍要运行\"即可;"),
            tr("  发布版附带SHA256校验值可供验证。"),
            "",
            tr("Q: KV cache信息从哪里获取?"),
            tr("A: vLLM启动日志中 grep 'KV cache size', 可用\"从日志自动获取\"工具"),
            tr("  直接从宿主机文件/容器日志/容器stdout筛选并一键填入。"),
        ]
        sections = [
            (tr("快速开始"), quick),
            (tr("1. SSH连接"), conn),
            (tr("2. 创建任务"), task),
            (tr("3. 任务列表"), tasklist),
            (tr("结果对比分析"), compare),
            (tr("常见问题"), faq),
        ]

        text.tag_configure("h1", font=("Segoe UI", 14, "bold"),
                            foreground=COLOR_PRIMARY)
        text.tag_configure("h2", font=("Segoe UI", 12, "bold"),
                            foreground=COLOR_TEXT)
        text.insert(tk.END, "AISBench PrefixTools\n", "h1")
        text.insert(tk.END, tr("远程AISBench测试任务创建与结果分析工具\n\n"))
        for title, lines in sections:
            text.insert(tk.END, title + "\n", "h2")
            for line in lines:
                text.insert(tk.END, line + "\n")
            text.insert(tk.END, "\n")
        text.config(state=tk.DISABLED)

        btn_frame = tk.Frame(dlg, bg=COLOR_BG)
        btn_frame.pack(fill=tk.X, pady=8)
        LocalizedButton(btn_frame, text=tr("关闭"), command=dlg.destroy,
                        font=("Segoe UI", 9), padx=16, pady=4).pack()
        self.root.bind("<F1>", lambda _e: self._show_usage_help())

    def _build_ui(self):
        """构建主界面"""
        self._build_menubar()

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
        """构建左侧导航栏: SSH连接 / 创建任务 / 任务列表 + 独立工具"""
        sidebar = tk.Frame(parent, bg=COLOR_CARD, width=200, relief=tk.SOLID, bd=1)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        sidebar.pack_propagate(False)

        # 标题
        title_lbl = LocalizedLabel(sidebar, text="AISBench\nPrefixTools", bg=COLOR_CARD,
                            fg=COLOR_PRIMARY, font=("Segoe UI", 14, "bold"),
                            justify=tk.LEFT)
        title_lbl.pack(padx=16, pady=(20, 16), anchor=tk.W)

        # 导航项
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
                if step <= self._max_reached_step() or step == self.TASKLIST_STEP:
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
        """返回用户可达到的最大步骤(任务列表页始终可达)"""
        return max(self.current_step, self.TASKLIST_STEP)

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
        """按当前语言重建主界面

        表单变量均在__init__创建且重建时直接复用, 输入值天然保留;
        这里只恢复界面派生状态(连接状态/镜像列表/用例表/任务列表/滚动位置)。
        """
        self.language_var.set(SUPPORTED_LANGUAGES.get(get_language(), "中文"))

        # 快照: 内容区滚动位置
        scroll = None
        if hasattr(self, "_content_canvas"):
            try:
                scroll = self._content_canvas.yview()
            except tk.TclError:
                scroll = None

        # 快照: SSH连接表单(conn_vars在每次构建时重建, 需手动恢复)
        conn_values = {}
        if hasattr(self, "conn_vars"):
            conn_values = {k: v.get() for k, v in self.conn_vars.items()}
        conn_password = self.conn_password.get() if hasattr(self, "conn_password") else ""
        conn_key = self.conn_key.get() if hasattr(self, "conn_key") else ""
        conn_status = None
        if hasattr(self, "conn_status_lbl"):
            conn_status = (self.conn_status_lbl.cget("text"),
                           self.conn_status_lbl.cget("fg"))
        residual_status = None
        if hasattr(self, "residual_status_lbl"):
            residual_status = (self.residual_status_lbl.cget("text"),
                               self.residual_status_lbl.cget("fg"))
        image_status = None
        if hasattr(self, "image_list_status"):
            image_status = (self.image_list_status.cget("text"),
                            self.image_list_status.cget("fg"))

        # 销毁并重建(菜单/侧边栏/内容区)
        if hasattr(self, "main_frame"):
            self.main_frame.destroy()
        self._build_ui()

        # 恢复SSH连接表单与状态
        for key, value in conn_values.items():
            if key in self.conn_vars:
                self.conn_vars[key].set(value)
        if conn_password:
            self.conn_password.set(conn_password)
        if conn_key:
            self.conn_key.set(conn_key)
        if conn_status:
            self.conn_status_lbl.config(text=conn_status[0], fg=conn_status[1])
        if self.ssh.connected:
            self.status_lbl.config(text="● 已连接", fg=COLOR_SUCCESS)
        if residual_status:
            self.residual_status_lbl.config(
                text=residual_status[0], fg=residual_status[1])
        if image_status:
            self.image_list_status.config(
                text=image_status[0], fg=image_status[1])

        # 恢复镜像/代码来源控件状态
        if self.remote_images:
            self._apply_remote_image_filter(update_selection=False)
        self._on_image_source_change()
        self._on_code_source_change()

        # 恢复测试用例表与计算明细(按当前语言重新渲染)
        self._refresh_test_tree()
        if self.designer.test_cases:
            self._show_calc_details()

        # 恢复任务列表
        self._refresh_task_table()
        if self.selected_task_id and self.task_manager.get(self.selected_task_id):
            self._select_task(self.selected_task_id, reset_log=True)

        # 回到原步骤(不跳转)并恢复滚动位置
        self._show_step(self.current_step)
        if scroll and hasattr(self, "_content_canvas"):
            self._content_canvas.yview_moveto(scroll[0])
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
        # (如日志栏/表格) 能随窗口弹性伸缩; 超出一屏时保持自然高度可滚动
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

        # 为每个页面创建Frame
        self.step_frames = []
        for i in range(len(self.STEP_TITLES)):
            frame = tk.Frame(self.content_container, bg=COLOR_BG)
            self.step_frames.append(frame)

        # 页面1: SSH连接
        self._build_step0_connection()
        # 页面2: 创建任务(任务资源 / 服务配置 / 测试参数 / 创建执行)
        self._build_step_header(
            self.step_frames[1], "步骤 2: 创建任务",
            "配置任务资源与测试用例; 创建后自动执行, 状态与日志在\"任务列表\"查看")
        self._build_task_resources_section()
        self._build_task_service_section()
        self._build_task_testcases_section()
        self._build_task_run_section()
        # 页面3: 任务列表
        self._build_tasklist_page()

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
        """分区①: 任务资源(任务名/镜像/代码/模型路径/临时部署目录)"""
        frame = self.step_frames[1]

        self.resources_section_header = self._build_section_header(
            frame, 1, "任务资源",
            "AISBench镜像 · 测试代码 · 模型权重路径 · 临时部署目录")

        form = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        form.pack(fill=tk.X, pady=(4, 8))
        row = 0

        # 任务名称: 留空自动使用 服务名_时间
        LocalizedLabel(form, text="任务名称:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W,
                                          padx=16, pady=(8, 4))
        name_frame = tk.Frame(form, bg=COLOR_CARD)
        name_frame.grid(row=row, column=1, columnspan=2, padx=16,
                        pady=(8, 4), sticky=tk.EW)
        tk.Entry(name_frame, textvariable=self.task_name_var, width=1,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        LocalizedLabel(name_frame, text=tr("留空自动: 服务名_时间"),
                       bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                       font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(8, 0))

        row += 1

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
        # 筛选结果数量提示(筛选时显示 x/y)
        self.remote_image_filter_hint = LocalizedLabel(
            self.remote_image_frame, text="", bg=COLOR_CARD,
            fg=COLOR_TEXT_MUTED, font=("Segoe UI", 7))
        self.remote_image_filter_hint.pack(anchor=tk.W, padx=(0, 4))
        # 镜像查询状态提示
        self.image_list_status = LocalizedLabel(
            self.remote_image_frame, text="尚未查询",
            bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 8), anchor=tk.W)
        self.image_list_status.pack(anchor=tk.W, padx=(0, 4))

        self.tar_upload_frame = tk.Frame(image_choice_frame, bg=COLOR_CARD)
        self.tar_upload_frame.grid(row=0, column=0, sticky=tk.EW)
        self.tar_upload_frame.grid_remove()
        tk.Entry(self.tar_upload_frame, textvariable=self.tar_path, width=1,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        LocalizedButton(self.tar_upload_frame, text="浏览...", command=self._browse_tar,
                  font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))
        LocalizedButton(self.tar_upload_frame, text="镜像下载链接", command=lambda: self._open_link(
                "https://github.com/rayn-zzz/aisbench_auto_tools_prefix/releases"),
                font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 0))

        row += 1

        # 测试代码来源: 程序内置 / 本地zip包
        LocalizedLabel(form, text="测试代码来源:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W,
                                          padx=16, pady=8)
        code_frame = tk.Frame(form, bg=COLOR_CARD)
        code_frame.grid(row=row, column=1, padx=16, pady=8, sticky=tk.W)
        LocalizedRadiobutton(code_frame, text="程序内置 (推荐)", variable=self.code_source_var,
                       value="builtin", bg=COLOR_CARD, font=("Segoe UI", 9),
                       command=self._on_code_source_change).pack(side=tk.LEFT)
        LocalizedRadiobutton(code_frame, text="本地 zip 包", variable=self.code_source_var,
                       value="zip", bg=COLOR_CARD, font=("Segoe UI", 9),
                       command=self._on_code_source_change).pack(side=tk.LEFT, padx=(12, 0))

        row += 1
        # zip路径(默认隐藏, 切换zip模式显示)
        image_choice2 = tk.Frame(form, bg=COLOR_CARD)
        image_choice2.grid(row=row, column=1, columnspan=2, padx=16,
                           pady=(0, 8), sticky=tk.EW)
        image_choice2.columnconfigure(0, weight=1, minsize=0)
        self.code_builtin_frame = tk.Frame(image_choice2, bg=COLOR_CARD)
        self.code_builtin_frame.grid(row=0, column=0, sticky=tk.EW)
        LocalizedLabel(self.code_builtin_frame, text=tr("内置代码随程序打包, 部署时自动上传"),
                       bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                       font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.code_zip_frame = tk.Frame(image_choice2, bg=COLOR_CARD)
        self.code_zip_frame.grid(row=0, column=0, sticky=tk.EW)
        self.code_zip_frame.grid_remove()
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

        # 临时部署目录(基目录): 用户可浏览选择; 每任务在其下自动创建独立子目录
        LocalizedLabel(form, text="临时部署目录:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W,
                                          padx=16, pady=(4, 8))
        workdir_frame = tk.Frame(form, bg=COLOR_CARD)
        workdir_frame.grid(row=row, column=1, columnspan=2, padx=16,
                           pady=(4, 2), sticky=tk.EW)
        workdir_frame.columnconfigure(0, weight=1)
        wd_entry = tk.Entry(workdir_frame, textvariable=self.work_dir_var, width=1,
                            font=("Segoe UI", 9))
        wd_entry.grid(row=0, column=0, sticky=tk.EW)
        LocalizedButton(workdir_frame, text="浏览远程目录",
                        command=self._browse_remote_work_dir,
                        font=("Segoe UI", 8)).grid(row=0, column=1, padx=(4, 0))
        LocalizedLabel(form, text=tr("任务在此目录下自动创建独立子目录, 部署完成后自动删除; "
                                     "默认 /tmp/AISBench_Prefix_Tools"),
                       bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8)
                       ).grid(row=row + 1, column=1, columnspan=2,
                              sticky=tk.W, padx=16, pady=(0, 8))

        form.columnconfigure(1, weight=1)

        # 残留容器清理: 支持清理上次未清理的 aisbench-test-* 容器
        residual_frame = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        residual_frame.pack(fill=tk.X, pady=(0, 4))
        LocalizedButton(residual_frame, text="清理残留容器", font=("Segoe UI", 8),
                  bg=COLOR_ERROR, fg="white", relief=tk.FLAT,
                  command=self._open_residual_container_dialog
                  ).pack(side=tk.LEFT, padx=12, pady=8)
        self.residual_status_lbl = LocalizedLabel(residual_frame, text="未扫描",
                                             bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                             font=("Segoe UI", 8))
        self.residual_status_lbl.pack(side=tk.LEFT, padx=8)

    def _build_task_service_section(self):
        """分区②: 服务配置(vLLM连接参数, 两行多列紧凑布局)"""
        frame = self.step_frames[1]

        self.service_section_header = self._build_section_header(
            frame, 2, "服务配置",
            "vLLM服务连接参数, 留空自动生成: 模型名ds · IP=执行机IP · 端口8000")

        form = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        form.pack(fill=tk.X, pady=(4, 8))

        # 两行多列: 每列 label在上/entry在下, 减少竖向占用
        fields = [
            (0, 0, "模型名称:", "model_name_var", 12),
            (0, 1, "服务 IP:", "host_ip_var", 16),
            (0, 2, "端口:", "host_port_var", 8),
            (0, 3, "API Key (可选):", "api_key_var", 14),
            (1, 0, "POD_INFO (多DP, ip:port,ip:port):", "pod_info_var", 0),
        ]
        for row, col, label, var_name, width in fields:
            cell = tk.Frame(form, bg=COLOR_CARD)
            cell.grid(row=row, column=col, sticky=tk.EW,
                      padx=(16 if col == 0 else 8), pady=(10 if row == 0 else 0, 4))
            LocalizedLabel(cell, text=label, bg=COLOR_CARD, fg=COLOR_TEXT,
                           font=("Segoe UI", 8)).pack(anchor=tk.W)
            entry = tk.Entry(cell, textvariable=getattr(self, var_name),
                             width=max(width, 1), font=("Segoe UI", 9))
            entry.pack(fill=tk.X, expand=True)

        # POD_INFO占满第二行剩余宽度
        pod_cell = tk.Frame(form, bg=COLOR_CARD)
        pod_cell.grid(row=1, column=1, columnspan=3, sticky=tk.EW,
                      padx=(8, 16), pady=(0, 10))
        LocalizedLabel(pod_cell, text=tr("留空时自动使用: 模型名称ds · IP=执行机IP · 端口8000"),
                       bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                       font=("Segoe UI", 8)).pack(anchor=tk.W)

        for col in range(4):
            form.columnconfigure(col, weight=1 if col in (1, 3) else 0)

    def _on_image_source_change(self):
        """切换镜像来源: 执行机已有镜像 / 本地tar包"""
        if self.image_source_var.get() == "existing":
            self.tar_upload_frame.grid_remove()
            self.remote_image_frame.grid()
            self.remote_image_filter_hint.pack()
        else:
            self.remote_image_frame.grid_remove()
            self.tar_upload_frame.grid()
            self.remote_image_filter_hint.pack_forget()

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

    def _open_remote_dir_browser(self, title, on_select, initial="/"):
        """通用远程目录浏览对话框(模型路径/临时部署目录共用)"""
        if not self.ssh.connected:
            showwarning("提示", "请先连接到远程主机")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()

        top = tk.Frame(dialog)
        top.pack(fill=tk.X, padx=8, pady=8)
        LocalizedLabel(top, text="路径:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        path_var = tk.StringVar(value=initial or "/")
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

        def _choose():
            on_select(path_var.get().strip())
            dialog.destroy()

        LocalizedButton(btn_frame, text="选择当前目录", bg=COLOR_PRIMARY, fg="white",
                 font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12,
                 command=_choose).pack(side=tk.RIGHT)
        LocalizedButton(btn_frame, text="取消", font=("Segoe UI", 9),
                 command=dialog.destroy).pack(side=tk.RIGHT, padx=8)

        self._list_remote_dir(listbox, path_var, dialog)

    def _browse_remote_model(self):
        """浏览远程目录选择模型权重路径"""
        self._open_remote_dir_browser(
            tr("浏览远程目录 - 选择模型路径"),
            lambda path: self.model_path_var.set(path))

    def _browse_remote_work_dir(self):
        """浏览远程目录选择临时部署目录(任务将在其下创建独立子目录)"""
        self._open_remote_dir_browser(
            tr("浏览远程目录 - 选择临时部署目录"),
            lambda path: self.work_dir_var.set(path),
            initial=self.work_dir_var.get().strip() or "/")

    def _browse_zip(self):
        path = filedialog.askopenfilename(
            title=tr("选择代码zip包"),
            filetypes=[("zip files", "*.zip"), ("All files", "*.*")]
        )
        if path:
            self.zip_path.set(path)

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


    def _open_link(self, url: str):
        """在浏览器中打开下载链接"""
        try:
            webbrowser.open(url)
        except Exception as e:
            showerror("打开失败", trf("无法打开链接: {url}\n{error}", url=url, error=e))

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
                    checked.discard(name)
                if clean_temp_var.get() and not self.task_manager.active_tasks():
                    work_dir = self.work_dir_var.get().strip()
                    if work_dir:
                        self.docker.remote_work_base = work_dir
                        self.docker.remove_work_dir(callback=_log_async)
                elif clean_temp_var.get():
                    _log(tr("有任务正在执行, 跳过临时目录清理\n"))
                _log("✓ 清理完成\n")
                _log(tr("如需再次执行测试用例, 请重新创建任务（重新部署容器）。\n"))

                def _done():
                    clean_btn.config(state=tk.NORMAL, text="清理选中")
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

    def _show_task_info_dialog(self, execute: bool):
        """任务全量信息确认/预览对话框

        execute=True: 创建任务前的确认(存在阻断问题时禁用执行按钮)
        execute=False: 预览当前表单汇总(未创建亦可查看)
        """
        inputs, issues = self._collect_task_inputs(silent=True)
        if inputs is None:
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(tr("确认任务信息") if execute else tr("预览任务信息"))
        dlg.geometry("820x680")
        dlg.transient(self.root)
        dlg.grab_set()

        body = tk.Frame(dlg, bg="white")
        body.pack(fill=tk.BOTH, expand=True)

        # 标题
        header = tk.Frame(body, bg="white")
        header.pack(fill=tk.X, padx=20, pady=(16, 8))
        title = tr("创建任务并执行") if execute else tr("当前任务配置预览")
        LocalizedLabel(header, text=title, bg="white", fg=COLOR_PRIMARY,
                       font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)
        task_name = inputs.resolved_name()
        LocalizedLabel(header, text=trf("任务名称: {name}", name=task_name),
                       bg="white", fg=COLOR_TEXT, font=("Segoe UI", 10)
                       ).pack(anchor=tk.W, pady=(2, 0))

        scroll = scrolledtext.ScrolledText(
            body, wrap=tk.WORD, font=("Segoe UI", 9),
            bg="white", fg=COLOR_TEXT, relief=tk.FLAT,
            padx=20, pady=8, height=10)
        scroll.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        # ---- 分区信息 ----
        image_desc = (inputs.selected_image
                      if inputs.image_mode == "existing"
                      else inputs.tar_path)
        code_desc = (tr("程序内置")
                     if inputs.code_source == "builtin" else inputs.zip_path)
        work_dir_desc = trf(
            "{base} (任务将创建独立子目录, 部署后自动删除)",
            base=inputs.work_dir_base)

        sections = [
            (tr("① 任务资源"), [
                (tr("AISBench镜像"), image_desc),
                (tr("测试代码"), code_desc),
                (tr("模型权重路径"), inputs.model_path),
                (tr("临时部署目录"), work_dir_desc),
            ]),
            (tr("② 服务配置"), [
                (tr("模型名称"), inputs.model_name),
                (tr("服务地址"),
                 f"{inputs.host_ip}:{inputs.host_port}"),
                (tr("API Key"), inputs.api_key or tr("(未设置)")),
                (tr("POD_INFO"), inputs.pod_info or tr("(未设置)")),
            ]),
            (tr("③ 测试参数"), [
                (tr("单个DP组KV cache"), f"{inputs.kv_cache} tokens"),
                (tr("DP组数"), inputs.dp),
                (tr("模型最大上下文"), f"{inputs.max_req_len} tokens"),
                (tr("前缀命中率"), inputs.repeat_rate),
                (tr("请求发送速率"),
                 trf("{rate} (0=Burst)", rate=inputs.request_rate)),
                (tr("输入长度"),
                 ", ".join(str(l) for l in inputs.input_lengths) or "-"),
                (tr("输出长度"),
                 ", ".join(str(l) for l in inputs.output_lengths) or "-"),
                (tr("测试用例数"), str(len(inputs.cases))),
            ]),
            (tr("④ 执行与输出"), [
                (tr("本地结果目录"), inputs.local_output),
                (tr("执行流程"),
                 tr("部署容器 → 写入config.py → 执行测试 → 下载并解析结果")),
            ]),
        ]

        scroll.tag_configure("h", font=("Segoe UI", 10, "bold"),
                             foreground=COLOR_PRIMARY)
        scroll.tag_configure("k", foreground=COLOR_TEXT_MUTED)
        for title_text, rows in sections:
            scroll.insert(tk.END, title_text + "\n", "h")
            for key, value in rows:
                scroll.insert(tk.END, f"  {key}: ", "k")
                scroll.insert(tk.END, f"{value}\n")
            scroll.insert(tk.END, "\n")

        # ---- 测试用例表格 ----
        cases_frame = tk.Frame(body, bg="white")
        cases_frame.pack(fill=tk.BOTH, expand=False, padx=12, pady=(0, 4))
        LocalizedLabel(cases_frame, text=tr("测试用例:"), bg="white",
                       fg=COLOR_TEXT, font=("Segoe UI", 9, "bold")
                       ).pack(anchor=tk.W, padx=8)
        columns = ("input", "output", "req", "prefix", "cc")
        tree = ttk.Treeview(cases_frame, columns=columns, show="headings",
                            height=min(5, max(1, len(inputs.cases))))
        headings = [("Input", 80), ("Output", 80), (tr("请求数"), 90),
                    (tr("前缀数量"), 100), (tr("并发数"), 80)]
        for col, (title_text, width) in zip(columns, headings):
            tree.heading(col, text=title_text)
            tree.column(col, width=width, anchor=tk.CENTER)
        tree.pack(fill=tk.X, padx=8, pady=(2, 8))
        for case in inputs.cases:
            tree.insert("", tk.END, values=(
                case.get("input_len", ""), case.get("output_len", ""),
                case.get("data_num_recommended", ""),
                case.get("prefix_num", ""),
                case.get("concurrency_recommended", ""),
            ))

        # ---- 问题提示 ----
        if issues:
            issue_frame = tk.Frame(body, bg="#fef2f2")
            issue_frame.pack(fill=tk.X, padx=12, pady=(0, 4))
            issue_lines = [tr("以下问题需处理后才能执行:")] + [
                f"  · {i}" for i in issues]
            LocalizedLabel(issue_frame, text="\n".join(issue_lines),
                           bg="#fef2f2", fg=COLOR_ERROR,
                           font=("Segoe UI", 8), justify=tk.LEFT
                           ).pack(anchor=tk.W, padx=10, pady=6)

        # ---- 按钮 ----
        btn_frame = tk.Frame(body, bg="white")
        btn_frame.pack(fill=tk.X, padx=20, pady=(4, 16))

        if execute:
            run_btn = LocalizedButton(
                btn_frame, text="🚀 确认创建并执行", bg=COLOR_PRIMARY,
                fg="white", font=("Segoe UI", 10, "bold"),
                relief=tk.FLAT, padx=20, pady=6,
                command=lambda: self._confirm_create_task(dlg, inputs, bool(issues)))
            run_btn.pack(side=tk.RIGHT)
            if issues:
                run_btn.config(state=tk.DISABLED)
        LocalizedButton(btn_frame, text=tr("关闭"), font=("Segoe UI", 9),
                        padx=16, pady=6, command=dlg.destroy
                        ).pack(side=tk.RIGHT, padx=8)

    def _confirm_create_task(self, dialog, inputs, has_issues: bool):
        """确认对话框中的执行入口"""
        if has_issues:
            return
        dialog.destroy()
        self._start_task_execution(inputs)

    # anchor: _copy_selected_task
    def _current_ssh_config(self) -> Optional[dict]:
        """当前SSH连接配置(每任务建立独立连接用)"""
        if not hasattr(self, "conn_vars") or not self.ssh.connected:
            return None
        return {
            "host": self.conn_vars["host"].get().strip(),
            "port": int(self.conn_vars["port"].get() or 22),
            "username": self.conn_vars["user"].get().strip(),
            "password": self.conn_password.get() if self.conn_password.get() else None,
            "key_path": self.conn_key.get().strip() or None,
        }

    def _collect_task_inputs(self, silent=False):
        """收集任务输入快照

        silent=True: 不弹窗, 返回(输入, 问题列表)供预览对话框展示
        silent=False: 弹窗提示阻断性问题, 返回(输入|None, 问题列表)
        """
        issues = []

        if not self.ssh.connected:
            issues.append(tr("未连接执行机"))
        if not hasattr(self, "conn_vars"):
            issues.append(tr("界面未初始化"))

        image_mode = self.image_source_var.get()
        selected_image = self.remote_image_var.get().strip()
        tar = self.tar_path.get().strip()
        if image_mode == "existing" and not selected_image:
            issues.append(tr("未选择执行机镜像"))
        if image_mode == "upload":
            if not tar:
                issues.append(tr("未选择镜像tar包"))
            elif not os.path.isfile(tar):
                issues.append(trf("镜像tar包不存在: {path}", path=tar))

        code_source = self.code_source_var.get()
        zip_path = self.zip_path.get().strip()
        if code_source == "zip":
            if not zip_path:
                issues.append(tr("未选择代码zip包"))
            elif not os.path.isfile(zip_path):
                issues.append(trf("代码zip包不存在: {path}", path=zip_path))
        elif code_source == "builtin":
            code_dir = self._get_bundled_code_dir()
            if not os.path.isdir(code_dir):
                issues.append(tr("未找到内置测试代码, 请改用本地zip包"))

        model = self.model_path_var.get().strip()
        if not model:
            issues.append(tr("未填写模型权重路径"))
        work_dir = self.work_dir_var.get().strip()
        if not work_dir:
            issues.append(tr("未填写临时部署目录"))

        # 服务参数(留空自动)
        host_ip = self.host_ip_var.get().strip()
        if not host_ip and hasattr(self, "conn_vars"):
            host_ip = self.conn_vars["host"].get().strip()
        host_port = self.host_port_var.get().strip() or "8000"
        if not host_port.isdigit():
            issues.append(tr("服务端口必须为数字"))

        # 测试参数
        kv = self.kv_cache_var.get().strip()
        if not kv or not kv.isdigit():
            issues.append(tr("单个DP组KV cache未填写或非数字"))
        dp = self.dp_var.get().strip() or "1"
        if not dp.isdigit():
            issues.append(tr("DP组数必须为数字"))
        max_req = self.max_req_len_var.get().strip()
        if not max_req or not max_req.isdigit():
            issues.append(tr("模型最大上下文未填写或非数字"))
        try:
            repeat = float(self.repeat_rate_var.get() or "0.9")
            if not (0 < repeat <= 1):
                issues.append(tr("前缀命中率需在(0,1]区间"))
        except ValueError:
            repeat = 0.9
            issues.append(tr("前缀命中率必须为数字"))
        rate_valid, rate_value = self._validate_request_rate()
        if not rate_valid:
            issues.append(tr("请求发送速率必须为数字(0=Burst)"))

        # 用例
        cases = [c.to_dict() for c in self.designer.test_cases]
        if not cases:
            issues.append(tr("未生成测试用例"))

        # 本地输出目录
        local_dir = self.local_output_var.get().strip()
        if not local_dir:
            issues.append(tr("未选择本地结果保存目录"))

        inputs = TaskInputs(
            name=self.task_name_var.get().strip(),
            image_mode=image_mode,
            selected_image=selected_image,
            tar_path=tar,
            code_source=code_source,
            zip_path=zip_path,
            model_path=model,
            work_dir_base=work_dir,
            model_name=self.model_name_var.get().strip() or "ds",
            host_ip=host_ip,
            host_port=host_port,
            api_key=self.api_key_var.get().strip(),
            pod_info=self.pod_info_var.get().strip(),
            kv_cache=kv,
            dp=dp,
            max_req_len=max_req,
            repeat_rate=self.repeat_rate_var.get().strip() or "0.9",
            request_rate=self.request_rate_var.get().strip() or "0",
            input_lengths=[l for l, v in self.input_length_vars.items() if v.get()],
            output_lengths=[l for l, v in self.output_length_vars.items() if v.get()],
            cases=cases,
            local_output=local_dir,
        )

        if not silent and issues:
            showwarning("提示", tr("请先完成以下配置:\n") +
                        "\n".join(f"  · {i}" for i in issues))
            return None, issues
        return inputs, issues

    def _validate_request_rate(self):
        """校验请求发送速率输入"""
        raw = self.request_rate_var.get().strip()
        if not raw:
            return True, 0
        try:
            value = float(raw)
            if value < 0:
                return False, None
            return True, value
        except ValueError:
            return False, None

    # anchor: _show_task_info_dialog
    def _create_task(self):
        """创建任务入口: 收集输入 → 全量信息确认 → 后台执行"""
        inputs, _issues = self._collect_task_inputs(silent=False)
        if inputs is None:
            return
        # 执行前同步最新速率(与用例生成时保持一致)
        if not self._sync_request_rate():
            showwarning("提示", tr("请求发送速率输入无效, 请输入数字\n(支持小数如 0.3; 0表示Burst模式)"))
            return
        # 弹出全量信息确认对话框(不直接执行)
        self._show_task_info_dialog(execute=True)

    def _start_task_execution(self, inputs: TaskInputs):
        """确认后创建任务并启动后台执行"""
        ssh_config = self._current_ssh_config()
        if not ssh_config:
            showwarning("提示", tr("请先连接到远程主机"))
            return

        task = self.task_manager.create_task(inputs, ssh_config)
        if not self.task_manager.start_task(task.id):
            showerror("错误", tr("任务启动失败"))
            return

        # 跳转任务列表查看执行状态
        self._show_step(self.TASKLIST_STEP)
        self._refresh_task_table(select=task.id)
        self._select_task(task.id, reset_log=True)
        self.task_status_lbl.config(
            text=trf("任务 {name} 已创建并开始执行", name=task.display_name),
            fg=COLOR_SUCCESS)

    def _build_task_testcases_section(self):
        """分区③: 测试参数(两行多列) + 输入/输出长度 + 用例表 + 计算明细"""
        frame = self.step_frames[1]

        self.testcases_section_header = self._build_section_header(
            frame, 3, "测试参数与用例",
            "KV cache信息可用\"从日志自动获取\"一键筛选; 勾选长度后生成用例")

        form = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        form.pack(fill=tk.X, pady=(4, 4))

        # ---- 第1行: KV cache / DP / 最大上下文 / 重复率 ----
        params_row1 = [
            ("单个DP组KV cache:", "kv_cache_var", 14),
            ("DP组数:", "dp_var", 6),
            ("模型最大上下文:", "max_req_len_var", 12),
            ("前缀命中率(0-1):", "repeat_rate_var", 8),
        ]
        for col, (label, var_name, width) in enumerate(params_row1):
            cell = tk.Frame(form, bg=COLOR_CARD)
            cell.grid(row=0, column=col, sticky=tk.EW,
                      padx=(16 if col == 0 else 8), pady=(8, 2))
            LocalizedLabel(cell, text=label, bg=COLOR_CARD, fg=COLOR_TEXT,
                           font=("Segoe UI", 8)).pack(anchor=tk.W)
            tk.Entry(cell, textvariable=getattr(self, var_name),
                     width=width, font=("Segoe UI", 9)).pack(fill=tk.X, expand=True)

        # ---- 第2行: 请求速率 + KV查询命令(复制/日志工具) ----
        rate_cell = tk.Frame(form, bg=COLOR_CARD)
        rate_cell.grid(row=1, column=0, sticky=tk.EW, padx=(16, 8), pady=(2, 8))
        LocalizedLabel(rate_cell, text="请求发送速率(0=Burst):", bg=COLOR_CARD,
                       fg=COLOR_TEXT, font=("Segoe UI", 8)).pack(anchor=tk.W)
        tk.Entry(rate_cell, textvariable=self.request_rate_var,
                 width=14, font=("Segoe UI", 9)).pack(fill=tk.X, expand=True)

        cmd_cell = tk.Frame(form, bg=COLOR_CARD)
        cmd_cell.grid(row=1, column=1, columnspan=3, sticky=tk.EW,
                      padx=(0, 16), pady=(2, 8))
        LocalizedLabel(cmd_cell, text="KV cache查询命令:", bg=COLOR_CARD,
                       fg=COLOR_TEXT, font=("Segoe UI", 8)).pack(anchor=tk.W)
        cmd_row = tk.Frame(cmd_cell, bg=COLOR_CARD)
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
        LocalizedButton(cmd_row, text="从日志自动获取 / 查看日志", font=("Segoe UI", 8),
                  relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white", padx=10,
                  command=self._open_log_browser).pack(side=tk.LEFT, padx=(6, 0))

        self.kv_hint_lbl = LocalizedLabel(
            form,
            text="KV cache size → 单个DP组KV cache (tokens);   Maximum concurrency → 模型最大上下文 (tokens)",
            bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, font=("Segoe UI", 7),
            anchor=tk.W, justify=tk.LEFT, wraplength=420)
        self.kv_hint_lbl.grid(row=2, column=0, columnspan=4,
                              sticky=tk.EW, padx=16, pady=(0, 8))

        def _wrap_kv_hint(event):
            self.kv_hint_lbl.config(wraplength=max(240, event.width - 8))
        form.bind("<Configure>", _wrap_kv_hint)

        for col in range(4):
            form.columnconfigure(col, weight=1 if col else 0)

        # ---- 输入长度选择(保持原横向勾选) ----
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

        # ---- 输出长度选择(保持原横向勾选) ----
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

        # ---- 生成按钮 ----
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

        # ---- 测试用例 + 计算明细 (拖拽分隔条调整两者占比) ----
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

    def _build_task_run_section(self):
        """分区④: 创建任务(本地结果目录 + 预览 + 创建)"""
        frame = self.step_frames[1]

        self.run_section_header = self._build_section_header(
            frame, 4, "创建任务",
            "确认全量信息后一键执行: 部署容器 → 写入config.py → 执行测试 → 下载结果")

        form = tk.Frame(frame, bg=COLOR_CARD, relief=tk.SOLID, bd=1)
        form.pack(fill=tk.X, pady=(4, 4))

        LocalizedLabel(form, text="本地结果保存目录:", bg=COLOR_CARD, fg=COLOR_TEXT,
               font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.W,
                                          padx=16, pady=(8, 8))
        out_frame = tk.Frame(form, bg=COLOR_CARD)
        out_frame.grid(row=0, column=1, padx=16, pady=(8, 8), sticky=tk.EW)
        out_frame.columnconfigure(0, weight=1)
        tk.Entry(out_frame, textvariable=self.local_output_var, width=1,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.EW)
        LocalizedButton(out_frame, text="浏览...", command=self._browse_local_output,
                        font=("Segoe UI", 8)).grid(row=0, column=1, padx=(4, 0))
        form.columnconfigure(1, weight=1)

        # 任务执行按钮: 预览(未创建亦可查看) + 创建任务(确认后执行)
        btn_frame = tk.Frame(frame, bg=COLOR_BG)
        btn_frame.pack(fill=tk.X, pady=(8, 4))

        self.create_task_btn = LocalizedButton(
            btn_frame, text="🚀 创建任务", bg=COLOR_PRIMARY,
            fg="white", font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            command=self._create_task)
        self.create_task_btn.pack(side=tk.LEFT)

        self.preview_task_btn = LocalizedButton(
            btn_frame, text="预览任务信息", bg=COLOR_BORDER,
            fg=COLOR_TEXT, font=("Segoe UI", 9),
            relief=tk.FLAT, padx=16, pady=6,
            command=lambda: self._show_task_info_dialog(execute=False))
        self.preview_task_btn.pack(side=tk.LEFT, padx=(8, 0))

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

    def _on_task_manager_change(self, _task):
        """任务状态变化回调(工作线程触发, 调度到主线程刷新)"""
        try:
            self.root.after(0, self._refresh_task_table)
        except tk.TclError:
            pass

    def _schedule_task_poll(self):
        """周期轮询任务状态与日志(500ms)"""
        if self._task_poll_id:
            try:
                self.root.after_cancel(self._task_poll_id)
            except (tk.TclError, ValueError):
                pass
        self._task_poll_id = self.root.after(500, self._poll_tasks)

    def _poll_tasks(self):
        """轮询: 刷新任务表格 + 更新选中任务日志"""
        self._task_poll_id = None
        try:
            # 仅在有任务时刷新表格(避免高频重建)
            if self.task_manager.tasks:
                self._refresh_task_table()
            task = (self.task_manager.get(self.selected_task_id)
                    if self.selected_task_id else None)
            if task:
                self._update_task_log_view()
        except tk.TclError:
            return
        self._schedule_task_poll()

    def _update_task_log_view(self, force=False):
        """增量更新选中任务的日志显示(含\\r单行覆盖的pending行)"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task or not hasattr(self, "task_log_text"):
            return
        try:
            new_lines, pending = task.log_buffer.poll()
        except Exception:
            return
        if not new_lines and not pending and not force:
            return

        text = self.task_log_text
        try:
            first, last = text.yview()
        except tk.TclError:
            first, last = 0.0, 1.0
        at_bottom = last >= 0.999

        text.config(state=tk.NORMAL)
        # 删除上一轮的pending显示
        if self._task_log_pending_shown:
            try:
                text.delete("pend_mark", "end-1c")
            except tk.TclError:
                pass
            self._task_log_pending_shown = False
        # 追加新完整行
        for line in new_lines:
            text.insert("end-1c", line + "\n")
        # 显示当前pending行
        if pending:
            text.insert("end-1c", pending)
            self._task_log_pending_shown = True
        text.config(state=tk.DISABLED)
        if at_bottom:
            text.see("end")

    def _refresh_task_table(self, select=None):
        """刷新任务列表表格(保留选择)"""
        if not hasattr(self, "task_tree"):
            return
        selected = select or self.selected_task_id
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)

        for task in self.task_manager.all_tasks():
            created = task.created_at.strftime("%Y-%m-%d %H:%M:%S")
            finished = (task.finished_at.strftime("%Y-%m-%d %H:%M:%S")
                        if task.finished_at else "-")
            result = (os.path.basename(task.csv_path)
                      if isinstance(task.csv_path, str) and task.csv_path else
                      (tr("失败") if task.status == TaskStatus.FAILED else "-"))
            values = (
                task.display_name, task.status_label(), created, finished,
                task.image_name or task.inputs.selected_image or task.inputs.tar_path,
                task.inputs.model_path, task.container_name or "-",
                result,
            )
            self.task_tree.insert("", tk.END, iid=task.id, values=values)

        if selected and self.task_tree.exists(selected):
            self.task_tree.selection_set(selected)
            self.task_tree.see(selected)
        self._update_task_action_states()

    def _on_task_selected(self, _event=None):
        """任务表格选择变化"""
        selection = self.task_tree.selection()
        if selection:
            self._select_task(selection[0])

    def _select_task(self, task_id, reset_log=False):
        """选中任务: 显示其日志与结果"""
        task = self.task_manager.get(task_id)
        if not task:
            return
        self.selected_task_id = task_id
        self.task_log_title_lbl.config(
            text=trf("{name} - {status}", name=task.display_name,
                     status=task.status_label()))
        if reset_log:
            task.log_buffer.reset_shown()
            self._task_log_pending_shown = False
            self.task_log_text.config(state=tk.NORMAL)
            self.task_log_text.delete("1.0", tk.END)
            self.task_log_text.config(state=tk.DISABLED)
        self._update_task_log_view(force=True)
        self._update_task_results_view()
        self._update_task_action_states()

    def _update_task_action_states(self):
        """按选中任务状态启停操作按钮"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not hasattr(self, "task_cancel_btn"):
            return
        if not task:
            self.task_cancel_btn.config(state=tk.DISABLED)
            self.task_cleanup_btn.config(state=tk.DISABLED)
            self.task_delete_btn.config(state=tk.DISABLED)
            self.task_open_result_btn.config(state=tk.DISABLED)
            return
        active = task.status in TaskStatus.ACTIVE
        self.task_cancel_btn.config(
            state=tk.NORMAL if active else tk.DISABLED)
        has_resources = bool(task.container_name or task.deploy_work_dir) \
            and not task.resources_cleaned
        self.task_cleanup_btn.config(
            state=tk.NORMAL if has_resources and not active else tk.DISABLED)
        self.task_delete_btn.config(
            state=tk.NORMAL if not active else tk.DISABLED)
        self.task_open_result_btn.config(
            state=tk.NORMAL if task.result_dir else tk.DISABLED)

    def _show_step(self, step):
        """显示指定页面"""
        if step < 0 or step >= len(self.step_frames):
            return

        for i, frame in enumerate(self.step_frames):
            if i == step:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

        self.current_step = step

        # 切换页面后重新同步内容区高度, 并回到顶部
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

        # 更新导航按钮
        self.prev_btn.config(state=tk.NORMAL if step > 0 else tk.DISABLED)
        if step == len(self.step_frames) - 1:
            self.next_btn.config(text="完成", command=self._finish)
        else:
            self.next_btn.config(text="下一步 >", command=self._next_step)

        # 页面特定刷新
        if step == 1:
            if self.ssh.connected and not self.remote_images:
                self._refresh_remote_images()
        elif step == self.TASKLIST_STEP:
            self._refresh_task_table()



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
        """退出前检查运行中任务与未清理容器

        返回True: 可立即退出; False: 用户取消或清理完成后自动退出
        """
        # 运行中任务: 直接退出会异常终止
        active = self.task_manager.active_tasks()
        if active:
            names = ", ".join(t.display_name for t in active[:5])
            msg = trf(
                "仍有 {count} 个任务正在执行:\n  {names}\n\n"
                "退出将导致任务异常终止。确定退出吗?",
                count=len(active), names=names)
            if not askyesno("任务执行中", msg, icon=messagebox.WARNING):
                return False
            return True

        # 有容器资源未清理的任务: 提醒清理
        with_container = self.task_manager.tasks_with_containers()
        if not with_container:
            return True

        names = ", ".join(t.container_name for t in with_container[:5])
        work_dirs = ", ".join(t.deploy_work_dir for t in with_container[:5]
                              if t.deploy_work_dir)
        msg = trf(
            "检测到 {count} 个任务的远程容器未清理:\n  {names}\n"
            "{work_dir_line}"
            "\n退出前是否清理?\n"
            "(是: 清理后退出  否: 直接退出保留容器  取消: 不退出)\n"
            "(未清理的容器下次连接时可通过\"清理残留容器\"删除)",
            count=len(with_container), names=names,
            work_dir_line=(trf("临时目录: {dirs}\n", dirs=work_dirs)
                           if work_dirs else ""))
        choice = askyesnocancel("清理提醒", msg, icon=messagebox.WARNING)
        if choice is None:
            return False
        if choice:
            self._exit_after_cleanup = True
            self._cleanup_all_task_resources()
            return False
        return True

    def _cleanup_all_task_resources(self):
        """退出前清理所有未清理任务的远程资源"""
        if not self.ssh.connected:
            # 未连接时无法清理, 直接退出
            self.root.destroy()
            return

        def _do_cleanup():
            for task in self.task_manager.tasks_with_containers():
                try:
                    self.task_manager.cleanup_task(
                        task.id, self.ssh, progress=lambda t: task.log(t))
                except Exception:
                    pass
            self.task_manager.shutdown()

            def _exit_now():
                try:
                    self.root.destroy()
                except tk.TclError:
                    pass
            self.root.after(0, _exit_now)

        threading.Thread(target=_do_cleanup, daemon=True).start()



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

    def _build_tasklist_page(self):
        """页面3: 任务列表(状态/日志/结果/管理)"""
        frame = self.step_frames[2]

        self._build_step_header(
            frame, "步骤 3: 任务列表",
            "查看任务运行状态与全量日志, 管理任务数据; 日志同时写入本地文件")

        # ---- 操作栏 ----
        actions = tk.Frame(frame, bg=COLOR_BG)
        actions.pack(fill=tk.X, pady=(0, 4))

        LocalizedButton(actions, text="刷新", font=("Segoe UI", 8),
                        command=lambda: self._refresh_task_table(select=self.selected_task_id)
                        ).pack(side=tk.LEFT)
        LocalizedButton(actions, text="复制新建", font=("Segoe UI", 8),
                        command=self._copy_selected_task
                        ).pack(side=tk.LEFT, padx=4)
        self.task_cancel_btn = LocalizedButton(
            actions, text="取消任务", font=("Segoe UI", 8),
            bg=COLOR_WARNING, fg="white", relief=tk.FLAT,
            command=self._cancel_selected_task)
        self.task_cancel_btn.pack(side=tk.LEFT, padx=4)
        self.task_cleanup_btn = LocalizedButton(
            actions, text="清理资源", font=("Segoe UI", 8),
            command=self._cleanup_selected_task)
        self.task_cleanup_btn.pack(side=tk.LEFT, padx=4)
        self.task_delete_btn = LocalizedButton(
            actions, text="删除数据", font=("Segoe UI", 8),
            bg=COLOR_ERROR, fg="white", relief=tk.FLAT,
            command=self._delete_selected_task)
        self.task_delete_btn.pack(side=tk.LEFT, padx=4)

        self.task_status_lbl = LocalizedLabel(
            actions, text="", bg=COLOR_BG, fg=COLOR_TEXT_MUTED,
            font=("Segoe UI", 8))
        self.task_status_lbl.pack(side=tk.LEFT, padx=10)

        # ---- 上下分割: 任务表格 / 日志+结果 ----
        self.task_paned = tk.PanedWindow(frame, orient=tk.VERTICAL,
                                         sashrelief=tk.RAISED, sashwidth=6,
                                         bg=COLOR_BORDER)
        self.task_paned.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # Pane 1: 任务表格
        table_pane = tk.Frame(self.task_paned, bg=COLOR_BG)
        self.task_paned.add(table_pane, minsize=170, stretch="always")

        columns = ("name", "status", "created", "finished",
                   "image", "model", "container", "result")
        self.task_tree = ttk.Treeview(table_pane, columns=columns,
                                       show="headings", height=6,
                                       selectmode="browse")
        headings = [
            (tr("任务名称"), 170), (tr("状态"), 80), (tr("创建时间"), 130),
            (tr("结束时间"), 130), (tr("镜像"), 170), (tr("模型路径"), 170),
            (tr("容器"), 150), (tr("结果"), 150),
        ]
        for col, (title, width) in zip(columns, headings):
            self.task_tree.heading(col, text=title)
            self.task_tree.column(col, width=width, anchor=tk.W,
                                  stretch=True)
        self.task_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        task_scrollbar = tk.Scrollbar(table_pane, orient=tk.VERTICAL,
                                      command=self.task_tree.yview)
        task_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.task_tree.config(yscrollcommand=task_scrollbar.set)
        self.task_tree.bind("<<TreeviewSelect>>", self._on_task_selected)

        # Pane 2: 日志 + 结果 (Notebook)
        detail_pane = tk.Frame(self.task_paned, bg=COLOR_BG)
        self.task_paned.add(detail_pane, minsize=220, stretch="always")

        self.task_detail_notebook = ttk.Notebook(detail_pane)
        self.task_detail_notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: 执行日志
        log_tab = tk.Frame(self.task_detail_notebook, bg=COLOR_BG)
        self.task_detail_notebook.add(log_tab, text=tr("执行日志"))

        log_header = tk.Frame(log_tab, bg=COLOR_BG)
        log_header.pack(fill=tk.X, pady=(4, 2))
        self.task_log_title_lbl = LocalizedLabel(
            log_header, text=tr("(选择任务后显示日志)"), bg=COLOR_BG,
            fg=COLOR_TEXT, font=("Segoe UI", 9, "bold"))
        self.task_log_title_lbl.pack(side=tk.LEFT)
        LocalizedButton(log_header, text="全屏显示", font=("Segoe UI", 8),
                        command=self._fullscreen_task_log
                        ).pack(side=tk.RIGHT)

        log_frame = tk.Frame(log_tab)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 4))
        self.task_log_text = scrolledtext.ScrolledText(
            log_frame, font=("Consolas", 8), bg="#0f172a", fg="#d1e7ff",
            wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT)
        self.task_log_text.pack(fill=tk.BOTH, expand=True)
        # pending行显示标记(支持\r单行覆盖刷新)
        self.task_log_text.mark_set("pend_mark", "end-1c")
        self.task_log_text.mark_gravity("pend_mark", "left")

        # Tab 2: 结果摘要
        result_tab = tk.Frame(self.task_detail_notebook, bg=COLOR_BG)
        self.task_detail_notebook.add(result_tab, text=tr("结果摘要"))

        result_header = tk.Frame(result_tab, bg=COLOR_BG)
        result_header.pack(fill=tk.X, pady=(4, 2))
        self.task_result_info_lbl = LocalizedLabel(
            result_header, text=tr("(任务完成后显示结果)"), bg=COLOR_BG,
            fg=COLOR_TEXT, font=("Segoe UI", 9, "bold"))
        self.task_result_info_lbl.pack(side=tk.LEFT)
        self.task_open_result_btn = LocalizedButton(
            result_header, text="打开结果目录", font=("Segoe UI", 8),
            state=tk.DISABLED, command=self._open_task_result_dir)
        self.task_open_result_btn.pack(side=tk.RIGHT)

        result_frame = tk.Frame(result_tab)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 4))
        res_columns = ("input", "output", "req", "maxcc", "cc",
                       "in_tput", "out_tput", "ttft", "tpot", "qps",
                       "hbm", "ext")
        self.task_result_tree = ttk.Treeview(
            result_frame, columns=res_columns, show="headings", height=5)
        res_headings = [
            ("Input", 70), ("Output", 70), (tr("请求数"), 70),
            (tr("最大并发"), 80), (tr("并发"), 60),
            (tr("输入吞吐"), 95), (tr("输出吞吐"), 95),
            ("TTFT", 90), ("TPOT", 90), ("QPS", 70),
            (tr("HBM命中%"), 90), (tr("外部命中%"), 90),
        ]
        for col, (title, width) in zip(res_columns, res_headings):
            self.task_result_tree.heading(col, text=title)
            self.task_result_tree.column(col, width=width, anchor=tk.CENTER)
        result_hscroll = tk.Scrollbar(result_frame, orient=tk.HORIZONTAL,
                                       command=self.task_result_tree.xview)
        result_vscroll = tk.Scrollbar(result_frame, orient=tk.VERTICAL,
                                       command=self.task_result_tree.yview)
        self.task_result_tree.config(yscrollcommand=result_vscroll.set,
                                     xscrollcommand=result_hscroll.set)
        self.task_result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        result_vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        result_hscroll.pack(side=tk.BOTTOM, fill=tk.X)

        self._refresh_task_table()

    # anchor: _update_task_results_view
    def _copy_selected_task(self):
        """复制选中任务的配置, 预填创建任务表单"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task:
            showwarning("提示", tr("请先选择任务"))
            return
        inputs = self.task_manager.copy_inputs(task.id)
        if not inputs:
            showwarning("提示", tr("无法读取任务配置"))
            return

        # 预填表单(本地文件路径可能已不存在, 保留原值由用户确认)
        self.task_name_var.set(inputs.name)
        self.image_source_var.set(inputs.image_mode)
        self.remote_image_var.set(inputs.selected_image)
        self.tar_path.set(inputs.tar_path)
        self.code_source_var.set(inputs.code_source)
        self.zip_path.set(inputs.zip_path)
        self.model_path_var.set(inputs.model_path)
        self.work_dir_var.set(inputs.work_dir_base)
        self.model_name_var.set(inputs.model_name)
        self.host_ip_var.set(inputs.host_ip)
        self.host_port_var.set(inputs.host_port)
        self.api_key_var.set(inputs.api_key)
        self.pod_info_var.set(inputs.pod_info)
        self.kv_cache_var.set(inputs.kv_cache)
        self.dp_var.set(inputs.dp)
        self.max_req_len_var.set(inputs.max_req_len)
        self.repeat_rate_var.set(inputs.repeat_rate)
        self.request_rate_var.set(inputs.request_rate)
        self.local_output_var.set(inputs.local_output)

        # 长度勾选与用例: 回填设计器后刷新表格
        for length, var in self.input_length_vars.items():
            var.set(length in (inputs.input_lengths or []))
        for length, var in self.output_length_vars.items():
            var.set(length in (inputs.output_lengths or []))
        if inputs.cases:
            from task_manager import build_designer_from_inputs
            self.designer = build_designer_from_inputs(inputs)
            self._refresh_test_tree()
            self._show_calc_details()

        self._on_image_source_change()
        self._on_code_source_change()
        self._show_step(1)
        self.task_status_lbl.config(
            text=trf("已复制任务 {name} 的配置到创建任务页", name=task.display_name),
            fg=COLOR_SUCCESS)

    def _cancel_selected_task(self):
        """取消运行中的任务"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task or task.status not in TaskStatus.ACTIVE:
            return
        if not askyesno(tr("确认取消"),
                        trf("确定取消任务 {name}?\n\n"
                            "执行阶段会停止容器以中断测试; "
                            "已产生的本地结果不受影响。",
                            name=task.display_name),
                        icon=messagebox.WARNING):
            return
        ok = self.task_manager.cancel_task(task.id)
        self.task_status_lbl.config(
            text=tr("已发送取消请求") if ok else tr("取消失败"),
            fg=COLOR_WARNING if ok else COLOR_ERROR)
        self._refresh_task_table()

    def _cleanup_selected_task(self):
        """清理选中任务的远程资源(容器+临时目录)"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task:
            return
        if not self.ssh.connected:
            showwarning("提示", tr("请先在步骤1连接执行机, 再清理任务资源"))
            return

        container_line = (trf("  容器: {name}\n", name=task.container_name)
                          if task.container_name else "")
        workdir_line = (trf("  临时目录: {dir}\n", dir=task.deploy_work_dir)
                        if task.deploy_work_dir else "")
        if not askyesno(
                "清理任务资源",
                trf("确认清理任务 {name} 的以下远程资源?\n\n"
                    "{container}{workdir}\n"
                    "清理后如需再次执行, 请重新创建任务。",
                    name=task.display_name,
                    container=container_line, workdir=workdir_line),
                icon=messagebox.WARNING):
            return

        self.task_cleanup_btn.config(state=tk.DISABLED)
        self.task_status_lbl.config(text=tr("清理中..."), fg=COLOR_TEXT_MUTED)

        def _do_cleanup():
            ok, msg = self.task_manager.cleanup_task(
                task.id, self.ssh,
                progress=lambda t: task.log(t))
            def _done():
                self.task_status_lbl.config(
                    text=msg, fg=COLOR_SUCCESS if ok else COLOR_ERROR)
                self._refresh_task_table()
                self._select_task(task.id, reset_log=False)
            self.root.after(0, _done)

        threading.Thread(target=_do_cleanup, daemon=True).start()

    def _delete_selected_task(self):
        """删除选中任务记录(可选同时删除本地数据文件)"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task:
            return

        files_desc = tr("本地日志") + " · " + tr("结果目录/CSV")
        choice = askyesnocancel(
            "删除任务数据",
            trf("删除任务 {name}?\n\n"
                "是 - 删除任务记录并删除其 {files}\n"
                "否 - 仅删除任务记录(保留本地文件)\n"
                "取消 - 不删除",
                name=task.display_name, files=files_desc),
            icon=messagebox.WARNING)
        if choice is None:
            return
        delete_files = choice is True

        ok = self.task_manager.delete_task(task.id, delete_files=delete_files)
        if ok:
            self.selected_task_id = None
            self._task_log_pending_shown = False
            self.task_log_text.config(state=tk.NORMAL)
            self.task_log_text.delete("1.0", tk.END)
            self.task_log_text.config(state=tk.DISABLED)
            self.task_log_title_lbl.config(text=tr("(选择任务后显示日志)"))
            self.task_status_lbl.config(
                text=tr("任务数据已删除") if delete_files else tr("任务记录已删除"),
                fg=COLOR_SUCCESS)
        else:
            self.task_status_lbl.config(text=tr("删除失败"), fg=COLOR_ERROR)
        self._refresh_task_table()
        self._update_task_results_view()

    def _update_task_results_view(self):
        """显示选中任务的结果摘要表"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task:
            return
        for item in self.task_result_tree.get_children():
            self.task_result_tree.delete(item)

        if task.results:
            for row in task.results:
                values = (
                    row.get("input_len", ""), row.get("output_len", ""),
                    row.get("total_req", ""), row.get("max_cc", ""),
                    row.get("cc", ""),
                    row.get("input_token_throughput", ""),
                    row.get("output_throughput", ""),
                    row.get("TTFT_avg", ""), row.get("TPOT_avg", ""),
                    row.get("qps", ""), row.get("hbm_hit_rate", ""),
                    row.get("external_hit_rate", ""),
                )
                self.task_result_tree.insert("", tk.END, values=values)
            self.task_result_info_lbl.config(
                text=trf("共 {count} 条结果  CSV: {csv}",
                         count=len(task.results), csv=task.csv_path))
        elif task.status == TaskStatus.COMPLETED:
            self.task_result_info_lbl.config(
                text=tr("测试完成但未提取到有效结果"))
        elif task.status in TaskStatus.ACTIVE:
            self.task_result_info_lbl.config(
                text=tr("任务执行中, 完成后显示结果"))
        else:
            self.task_result_info_lbl.config(text=tr("(任务完成后显示结果)"))

    def _open_task_result_dir(self):
        """打开选中任务的结果目录"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task or not task.result_dir:
            return
        path = os.path.normpath(task.result_dir)
        if not os.path.isdir(path):
            showwarning("提示", trf("结果目录不存在: {path}", path=path))
            return
        try:
            os.startfile(path)  # noqa: S606 - Windows资源管理器
        except OSError as exc:
            showerror("错误", trf("无法打开目录: {error}", error=exc))

    # anchor: _schedule_task_poll
    def _fullscreen_task_log(self):
        """全屏查看选中任务的执行日志"""
        task = (self.task_manager.get(self.selected_task_id)
                if self.selected_task_id else None)
        if not task:
            showwarning("提示", tr("请先选择任务"))
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(trf("任务日志 - {name}", name=task.display_name))
        dlg.geometry("1000x700")
        dlg.transient(self.root)

        header = tk.Frame(dlg, bg=COLOR_BG)
        header.pack(fill=tk.X, padx=10, pady=(10, 4))
        info = trf("{name} · {status} · 创建于 {time}",
                   name=task.display_name, status=task.status_label(),
                   time=task.created_at.strftime("%Y-%m-%d %H:%M:%S"))
        LocalizedLabel(header, text=info, bg=COLOR_BG, fg=COLOR_TEXT,
                       font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        LocalizedButton(header, text=tr("复制全部"), font=("Segoe UI", 8),
                        command=lambda: self._copy_task_log(dlg, text_widget)
                        ).pack(side=tk.RIGHT, padx=4)
        LocalizedButton(header, text=tr("关闭"), font=("Segoe UI", 8),
                        command=dlg.destroy).pack(side=tk.RIGHT)

        text_widget = scrolledtext.ScrolledText(
            dlg, font=("Consolas", 9), bg="#0f172a", fg="#d1e7ff",
            wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # 展示当前全部日志(完整行 + pending)
        with task.log_buffer._lock:
            lines = list(task.log_buffer.lines)
            pending = task.log_buffer._pending
        text_widget.config(state=tk.NORMAL)
        for line in lines:
            text_widget.insert(tk.END, line + "\n")
        if pending:
            text_widget.insert(tk.END, pending)
        text_widget.config(state=tk.DISABLED)
        text_widget.see(tk.END)

    def _copy_task_log(self, dlg, text_widget):
        """复制全屏日志内容到剪贴板"""
        try:
            content = text_widget.get("1.0", "end-1c")
            dlg.clipboard_clear()
            dlg.clipboard_append(content)
            showinfo("提示", tr("日志已复制到剪贴板"))
        except tk.TclError:
            pass

    # anchor: _show_usage_help
    def _show_about(self):
        """软件详情: 版本/技术栈/仓库链接"""
        dlg = tk.Toplevel(self.root)
        dlg.title(tr("关于 AISBench PrefixTools"))
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        body = tk.Frame(dlg, bg="white", padx=32, pady=24)
        body.pack(fill=tk.BOTH, expand=True)

        LocalizedLabel(body, text="AISBench PrefixTools", bg="white",
                       fg=COLOR_PRIMARY, font=("Segoe UI", 16, "bold")
                       ).pack(anchor=tk.W)
        LocalizedLabel(body, text=trf("版本: {version}", version=self.APP_VERSION),
                       bg="white", fg=COLOR_TEXT, font=("Segoe UI", 10)
                       ).pack(anchor=tk.W, pady=(6, 0))
        LocalizedLabel(body, text=tr("远程AISBench测试任务创建与结果分析工具"),
                       bg="white", fg=COLOR_TEXT_MUTED, font=("Segoe UI", 9)
                       ).pack(anchor=tk.W, pady=(2, 12))

        info_lines = [
            trf("运行环境: Python {py} / Tk {tk}",
                py=sys.version.split()[0], tk=tk.TkVersion),
            tr("任务引擎: 每任务独立SSH连接与容器, 本地日志与元数据持久化"),
            tr("结果分析: CSV差异对比与图表导出"),
        ]
        info = "\n".join(info_lines)
        LocalizedLabel(body, text=info, bg="white", fg=COLOR_TEXT,
                       font=("Segoe UI", 9), justify=tk.LEFT
                       ).pack(anchor=tk.W, pady=(0, 12))

        repo_url = "https://github.com/ucm-system/AISBench-Prefix-Tools"
        link = LocalizedLabel(body, text=repo_url,
                              bg="white", fg=COLOR_PRIMARY,
                              font=("Segoe UI", 9), cursor="hand2")
        link.pack(anchor=tk.W)
        link.bind("<Button-1>", lambda _e: self._open_link(repo_url))

        LocalizedButton(body, text=tr("关闭"), command=dlg.destroy,
                        font=("Segoe UI", 9), padx=16, pady=4
                        ).pack(anchor=tk.E, pady=(16, 0))

def main():
    app = WizardApp()
    app.run()


if __name__ == "__main__":
    main()
