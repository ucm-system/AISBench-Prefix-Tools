"""
远程日志工具 - 从宿主机/容器中选择日志文件:
1. 筛选 vLLM KV cache 信息并一键填入测试参数
2. 查看指定日志文件内容(尾部)
"""

import re
import shlex
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from i18n import LocalizedButton, LocalizedCheckbutton, LocalizedLabel, LocalizedLabelFrame, LocalizedRadiobutton, showinfo, showerror, showwarning
from typing import Optional, List, Tuple, Callable

from ssh_manager import SSHManager


# KV cache 查询命令 (与界面展示保持一致)
KV_GREP_COMMAND = "cat vllm_serve.log | grep -e 'GPU KV cache size' -e 'Maximum concurrency'"

# 样式常量 (与 main.py 保持一致)
COLOR_BG = "#f8fafc"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#e2e8f0"
COLOR_TEXT = "#1e293b"
COLOR_TEXT_MUTED = "#64748b"
COLOR_PRIMARY = "#2563eb"
COLOR_SUCCESS = "#16a34a"
COLOR_ERROR = "#dc2626"
COLOR_WARNING = "#d97706"

# 查看日志时加载文件尾部的最大字节数 / docker logs 行数
VIEW_TAIL_BYTES = 2 * 1024 * 1024
VIEW_DOCKER_LOGS_LINES = 5000


def _q(value: str) -> str:
    """POSIX shell 引用, 用于远程命令中的路径/容器名"""
    return shlex.quote(value)


class RemoteLogBrowser:
    """远程日志选择/筛选/查看对话框

    - 服务器: 当前执行机 或 其他服务器(临时连接, 关闭对话框时自动断开)
    - 日志来源: 宿主机文件 / 指定容器内文件 / 容器 stdout 日志(docker logs)
    - 筛选: 对选定日志执行 KV cache grep, 解析数值并可一键填入测试参数
    - 查看: 加载日志尾部内容到独立窗口 (大文件只取尾部, 避免卡顿)
    """

    def __init__(self, parent: tk.Misc, main_ssh: SSHManager,
                 kv_cache_var: Optional[tk.StringVar] = None,
                 max_req_len_var: Optional[tk.StringVar] = None,
                 on_command: Optional[Callable[[str], None]] = None):
        self.parent = parent
        self.main_ssh = main_ssh
        self.kv_cache_var = kv_cache_var
        self.max_req_len_var = max_req_len_var
        self.on_command = on_command

        self.other_ssh: Optional[SSHManager] = None
        self.current_file = ""
        self.parsed_kv: Optional[int] = None
        self.parsed_max_len: Optional[int] = None
        self._entries: List[dict] = []

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("远程日志工具 - 筛选 KV cache / 查看日志")
        self.dialog.geometry("780x660")
        self.dialog.minsize(680, 560)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.configure(bg=COLOR_BG)
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

        # 默认加载根目录 (当前服务器已连接时)
        ssh = self._active_ssh()
        if ssh and ssh.connected:
            self._load_dir("/")

    # ============================================================
    #  UI 构建
    # ============================================================

    def _build_ui(self):
        main = tk.Frame(self.dialog, bg=COLOR_BG)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_server_section(main)
        self._build_source_section(main)
        self._build_browser_section(main)
        self._build_actions_section(main)
        self._build_results_section(main)

    def _build_server_section(self, parent):
        box = LocalizedLabelFrame(parent, text=" 服务器 ", bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.pack(fill=tk.X, padx=10, pady=(10, 4))

        current_label = "当前执行机 (未连接)"
        if self.main_ssh and self.main_ssh.connected:
            current_label = f"当前执行机 ({self.main_ssh.host}:{self.main_ssh.port})"

        self.server_var = tk.StringVar(value="current")
        radio_row = tk.Frame(box, bg=COLOR_CARD)
        radio_row.pack(fill=tk.X, padx=10, pady=(6, 2))
        LocalizedRadiobutton(radio_row, text=current_label, variable=self.server_var,
                       value="current", command=self._on_server_mode_change,
                       bg=COLOR_CARD, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        LocalizedRadiobutton(radio_row, text="其他服务器", variable=self.server_var,
                       value="other", command=self._on_server_mode_change,
                       bg=COLOR_CARD, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=20)

        # 其他服务器: 连接信息 (默认隐藏)
        self.other_frame = tk.Frame(box, bg=COLOR_CARD)

        fields = tk.Frame(self.other_frame, bg=COLOR_CARD)
        fields.pack(fill=tk.X, padx=10, pady=2)
        self.other_vars = {
            "host": tk.StringVar(),
            "port": tk.StringVar(value="22"),
            "user": tk.StringVar(value="root"),
            "password": tk.StringVar(),
            "key": tk.StringVar(),
        }
        for text, key, width in (("IP:", "host", 14), ("端口:", "port", 6),
                                 ("用户名:", "user", 10)):
            LocalizedLabel(fields, text=text, bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                     font=("Segoe UI", 8)).pack(side=tk.LEFT)
            tk.Entry(fields, textvariable=self.other_vars[key], width=width,
                     font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(2, 10))

        auth_row = tk.Frame(self.other_frame, bg=COLOR_CARD)
        auth_row.pack(fill=tk.X, padx=10, pady=2)
        LocalizedLabel(auth_row, text="密码:", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        tk.Entry(auth_row, textvariable=self.other_vars["password"], width=18,
                 show="*", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(2, 10))
        LocalizedLabel(auth_row, text="密钥:", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        tk.Entry(auth_row, textvariable=self.other_vars["key"], width=28,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=2)
        LocalizedButton(auth_row, text="浏览", font=("Segoe UI", 7), relief=tk.FLAT,
                  bg=COLOR_BORDER, padx=6,
                  command=self._browse_key).pack(side=tk.LEFT, padx=4)

        conn_row = tk.Frame(self.other_frame, bg=COLOR_CARD)
        conn_row.pack(fill=tk.X, padx=10, pady=(2, 6))
        self.connect_btn = LocalizedButton(conn_row, text="连接", font=("Segoe UI", 8, "bold"),
                                     relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white",
                                     padx=14, command=self._connect_other)
        self.connect_btn.pack(side=tk.LEFT)
        self.conn_status_lbl = LocalizedLabel(conn_row, text="未连接", bg=COLOR_CARD,
                                        fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8))
        self.conn_status_lbl.pack(side=tk.LEFT, padx=10)

    def _build_source_section(self, parent):
        box = LocalizedLabelFrame(parent, text=" 日志来源 ", bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.pack(fill=tk.X, padx=10, pady=4)

        self.source_var = tk.StringVar(value="host")
        radio_row = tk.Frame(box, bg=COLOR_CARD)
        radio_row.pack(fill=tk.X, padx=10, pady=(6, 2))
        for text, value in (("宿主机文件", "host"),
                            ("容器内文件", "container"),
                            ("容器日志(docker logs)", "docker_logs")):
            LocalizedRadiobutton(radio_row, text=text, variable=self.source_var,
                           value=value, command=self._on_source_change,
                           bg=COLOR_CARD, font=("Segoe UI", 9)).pack(side=tk.LEFT,
                                                                   padx=(0, 14))

        ctr_row = tk.Frame(box, bg=COLOR_CARD)
        ctr_row.pack(fill=tk.X, padx=10, pady=(2, 6))
        LocalizedLabel(ctr_row, text="容器:", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.container_var = tk.StringVar()
        self.container_combo = ttk.Combobox(ctr_row, textvariable=self.container_var,
                                            state="readonly", width=36,
                                            font=("Segoe UI", 8))
        self.container_combo.pack(side=tk.LEFT, padx=6)
        LocalizedButton(ctr_row, text="刷新容器列表", font=("Segoe UI", 7), relief=tk.FLAT,
                  bg=COLOR_BORDER, padx=8,
                  command=self._refresh_containers).pack(side=tk.LEFT)
        self.container_status_lbl = LocalizedLabel(ctr_row, text="", bg=COLOR_CARD,
                                             fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8))
        self.container_status_lbl.pack(side=tk.LEFT, padx=10)

    def _build_browser_section(self, parent):
        box = LocalizedLabelFrame(parent, text=" 文件浏览 (双击进入目录, 单击选择文件) ",
                            bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        path_row = tk.Frame(box, bg=COLOR_CARD)
        path_row.pack(fill=tk.X, padx=10, pady=(6, 2))
        LocalizedLabel(path_row, text="路径:", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value="/")
        path_entry = tk.Entry(path_row, textvariable=self.path_var, width=48,
                              font=("Segoe UI", 8))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        path_entry.bind("<Return>", lambda event: self._load_dir())
        LocalizedButton(path_row, text="前往", font=("Segoe UI", 7), relief=tk.FLAT,
                  bg=COLOR_BORDER, padx=8,
                  command=lambda: self._load_dir()).pack(side=tk.LEFT)

        list_frame = tk.Frame(box, bg=COLOR_CARD)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 6))
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_list = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                    font=("Segoe UI", 9), activestyle="dotbox")
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_list.yview)
        self.file_list.bind("<<ListboxSelect>>", self._on_list_select)
        self.file_list.bind("<Double-Button-1>", self._on_list_double_click)

        self.file_lbl = LocalizedLabel(box, text="当前文件: (未选择)", bg=COLOR_CARD,
                                 fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8), anchor=tk.W)
        self.file_lbl.pack(fill=tk.X, padx=10, pady=(0, 6))

    def _build_actions_section(self, parent):
        row = tk.Frame(parent, bg=COLOR_BG)
        row.pack(fill=tk.X, padx=10, pady=4)

        self.grep_btn = LocalizedButton(row, text="筛选 KV cache", font=("Segoe UI", 9, "bold"),
                                  relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white",
                                  padx=14, command=self._do_grep)
        self.grep_btn.pack(side=tk.LEFT)
        self.view_btn = LocalizedButton(row, text="查看日志", font=("Segoe UI", 9),
                                  relief=tk.FLAT, bg=COLOR_CARD, fg=COLOR_PRIMARY,
                                  padx=14, command=self._view_log)
        self.view_btn.pack(side=tk.LEFT, padx=8)
        self.action_status_lbl = LocalizedLabel(row, text="", bg=COLOR_BG,
                                          fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8))
        self.action_status_lbl.pack(side=tk.LEFT, padx=12)

    def _build_results_section(self, parent):
        box = LocalizedLabelFrame(parent, text=" 筛选结果 ", bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 4))

        self.result_text = scrolledtext.ScrolledText(box, height=6, font=("Consolas", 8),
                                                     bg="#f0f5ff", fg=COLOR_TEXT,
                                                     wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 2))
        self.result_text.insert("1.0", "(点击'筛选 KV cache'后显示 grep 结果)")
        self.result_text.config(state=tk.DISABLED)

        bottom = tk.Frame(box, bg=COLOR_CARD)
        bottom.pack(fill=tk.X, padx=10, pady=(2, 8))
        self.parsed_lbl = LocalizedLabel(bottom, text="", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                   font=("Segoe UI", 8), anchor=tk.W)
        self.parsed_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.fill_btn = LocalizedButton(bottom, text="填入参数", font=("Segoe UI", 9, "bold"),
                                  relief=tk.FLAT, bg=COLOR_SUCCESS, fg="white",
                                  padx=12, state=tk.DISABLED,
                                  command=self._fill_params)
        self.fill_btn.pack(side=tk.RIGHT)
        LocalizedButton(bottom, text="关闭", font=("Segoe UI", 9), relief=tk.FLAT,
                  bg=COLOR_CARD, fg=COLOR_TEXT, padx=12,
                  command=self._on_close).pack(side=tk.RIGHT, padx=(0, 8))

    # ============================================================
    #  服务器切换 / 其他服务器连接
    # ============================================================

    def _active_ssh(self) -> Optional[SSHManager]:
        if self.server_var.get() == "other":
            return self.other_ssh
        return self.main_ssh

    def _on_server_mode_change(self):
        if self.server_var.get() == "other":
            self.other_frame.pack(fill=tk.X, padx=6, pady=2)
        else:
            self.other_frame.pack_forget()
            self._disconnect_other()
        self._reset_after_server_change()

    def _reset_after_server_change(self):
        self.current_file = ""
        self.file_lbl.config(text="当前文件: (未选择)", fg=COLOR_TEXT_MUTED)
        self.container_combo["values"] = []
        self.container_var.set("")
        self._set_container_status("")
        self.path_var.set("/")
        self._set_entries([])
        ssh = self._active_ssh()
        if ssh and ssh.connected:
            self._load_dir("/")

    def _browse_key(self):
        path = filedialog.askopenfilename(
            parent=self.dialog, title="选择密钥文件",
            filetypes=[("密钥文件", "*.pem *.key *.rsa *.ed25519"),
                       ("所有文件", "*.*")])
        if path:
            self.other_vars["key"].set(path)

    def _connect_other(self):
        host = self.other_vars["host"].get().strip()
        try:
            port = int(self.other_vars["port"].get().strip() or "22")
        except ValueError:
            showwarning("提示", "端口必须为数字", parent=self.dialog)
            return
        user = self.other_vars["user"].get().strip()
        password = self.other_vars["password"].get() or None
        key_path = self.other_vars["key"].get().strip() or None

        if not host or not user:
            showwarning("提示", "请填写IP和用户名", parent=self.dialog)
            return
        if not password and not key_path:
            showwarning("提示", "请填写密码或密钥文件路径",
                                   parent=self.dialog)
            return

        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self._set_conn_status("正在连接...", COLOR_WARNING)

        def work():
            ssh = SSHManager()
            ok, msg = ssh.connect(host, port, user, password, key_path)

            def done():
                self.connect_btn.config(state=tk.NORMAL, text="连接")
                if ok:
                    self._disconnect_other()
                    self.other_ssh = ssh
                    self._set_conn_status(msg, COLOR_SUCCESS)
                    self._reset_after_server_change()
                else:
                    self._set_conn_status(msg, COLOR_ERROR)

            self.dialog.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _disconnect_other(self):
        if self.other_ssh and self.other_ssh.connected:
            self.other_ssh.disconnect()
        self.other_ssh = None
        self._set_conn_status("未连接", COLOR_TEXT_MUTED)

    def _set_conn_status(self, text: str, color: str = COLOR_TEXT_MUTED):
        self.conn_status_lbl.config(text=text, fg=color)

    def _on_close(self):
        self._disconnect_other()
        self.dialog.destroy()

    # ============================================================
    #  日志来源切换 / 容器列表
    # ============================================================

    def _source_mode(self) -> str:
        return self.source_var.get()

    def _on_source_change(self):
        mode = self._source_mode()
        self.current_file = ""

        if mode == "docker_logs":
            # docker logs 模式无需选择文件
            self.file_list.config(state=tk.DISABLED)
            self.file_lbl.config(text="当前文件: docker logs 输出 (无需选择文件)",
                                 fg=COLOR_TEXT)
            self._set_entries([])
        else:
            self.file_list.config(state=tk.NORMAL)
            self.file_lbl.config(text="当前文件: (未选择)", fg=COLOR_TEXT_MUTED)
            if mode == "container" and not self.container_var.get():
                # 容器未选: 先刷新容器列表, 选择后再浏览
                self._set_action_status("请先选择容器", COLOR_WARNING)
            else:
                ssh = self._active_ssh()
                if ssh and ssh.connected:
                    self._load_dir(self.path_var.get().strip() or "/")

        if mode in ("container", "docker_logs") and not self.container_combo["values"]:
            self._refresh_containers()

    def _refresh_containers(self):
        ssh = self._active_ssh()
        if ssh is None or not ssh.connected:
            self._set_container_status("未连接服务器", COLOR_ERROR)
            return

        self._set_container_status("获取容器列表中...", COLOR_WARNING)

        def work():
            code, out, err = ssh.execute(
                "docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}'", timeout=30)

            def done():
                if code != 0:
                    lines = (err.strip() or out.strip() or f"exit={code}").splitlines()
                    self._set_container_status(f"获取失败: {lines[-1]}", COLOR_ERROR)
                    return
                names = []
                for line in out.strip().splitlines():
                    parts = line.split("|", 2)
                    if parts and parts[0].strip():
                        names.append(parts[0].strip())
                self.container_combo["values"] = names
                if names:
                    if not self.container_var.get() or self.container_var.get() not in names:
                        self.container_var.set(names[0])
                    self._set_container_status(f"共 {len(names)} 个运行中容器",
                                               COLOR_SUCCESS)
                else:
                    self.container_var.set("")
                    self._set_container_status("未发现运行中的容器", COLOR_WARNING)

            self.dialog.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _set_container_status(self, text: str, color: str = COLOR_TEXT_MUTED):
        self.container_status_lbl.config(text=text, fg=color)

    # ============================================================
    #  目录/文件浏览
    # ============================================================

    def _load_dir(self, path: str = None):
        ssh = self._active_ssh()
        if ssh is None or not ssh.connected:
            showwarning("提示", "请先连接服务器", parent=self.dialog)
            return
        if self._source_mode() == "docker_logs":
            return
        if self._source_mode() == "container" and not self.container_var.get():
            showwarning("提示", "请先选择容器", parent=self.dialog)
            return

        if path is None:
            path = self.path_var.get().strip() or "/"
        path = path.rstrip("/") or "/"
        self.path_var.set(path)
        self._set_action_status("加载目录中...", COLOR_WARNING)

        def work():
            try:
                if self._source_mode() == "container":
                    container = self.container_var.get()
                    cmd = f"docker exec {_q(container)} ls -la {_q(path)}"
                    code, out, err = ssh.execute(cmd, timeout=30)
                    if code != 0:
                        msg = err.strip() or out.strip() or f"exit={code}"
                        last = msg.splitlines()[-1] if msg.splitlines() else msg
                        self.dialog.after(0, lambda: self._set_action_status(
                            f"列出目录失败: {last}", COLOR_ERROR))
                        return
                    entries = self._parse_ls_la(out)
                else:
                    entries = ssh.list_dir(path)

                def done():
                    self._set_entries(entries, path)
                    if entries:
                        self._set_action_status(f"已加载 {len(entries)} 项",
                                                COLOR_SUCCESS)
                    else:
                        self._set_action_status("目录为空", COLOR_WARNING)

                self.dialog.after(0, done)
            except Exception as exc:
                self.dialog.after(0, lambda: self._set_action_status(
                    f"列出目录失败: {exc}", COLOR_ERROR))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _parse_ls_la(out: str) -> List[dict]:
        """解析 ls -la 输出为 [{name, type, size}]"""
        entries = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("total ") or line.endswith(":"):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            perms, _links, _owner, _group, size, *_date, name = parts
            if name in (".", ".."):
                continue
            try:
                size_val = int(size)
            except ValueError:
                size_val = 0
            entries.append({
                "name": name,
                "type": "dir" if perms.startswith("d") else "file",
                "size": size_val,
            })
        return sorted(entries, key=lambda e: (e["type"] != "dir", e["name"]))

    def _set_entries(self, entries: List[dict], path: str = None):
        self._entries = []
        self.file_list.delete(0, tk.END)

        current = path if path is not None else self.path_var.get()
        if current and current != "/":
            self._entries.append({"name": "..", "type": "parent"})
            self.file_list.insert(tk.END, "../ (上级目录)")

        for entry in entries:
            self._entries.append(entry)
            if entry["type"] == "dir":
                self.file_list.insert(tk.END, f"[DIR] {entry['name']}")
            else:
                size = entry.get("size", 0)
                size_mb = size / 1024 / 1024
                if size_mb >= 1024:
                    size_str = f"{size_mb / 1024:.1f}GB"
                elif size_mb >= 0.1:
                    size_str = f"{size_mb:.1f}MB"
                else:
                    size_str = f"{size / 1024:.1f}KB"
                self.file_list.insert(tk.END, f"    {entry['name']}  ({size_str})")

    @staticmethod
    def _join_path(base: str, name: str) -> str:
        base = base.rstrip("/")
        return f"{base}/{name}" if base else f"/{name}"

    @staticmethod
    def _parent_path(path: str) -> str:
        stripped = path.rstrip("/")
        if not stripped or stripped == "/":
            return "/"
        return stripped.rsplit("/", 1)[0] or "/"

    def _on_list_select(self, _event):
        selection = self.file_list.curselection()
        if not selection:
            return
        entry = self._entries[selection[0]]
        if entry["type"] != "file":
            return
        path = self._join_path(self.path_var.get(), entry["name"])
        self.current_file = path
        self.file_lbl.config(text=f"当前文件: {path}", fg=COLOR_TEXT)

    def _on_list_double_click(self, _event):
        selection = self.file_list.curselection()
        if not selection:
            return
        entry = self._entries[selection[0]]
        if entry["type"] == "parent":
            self._load_dir(self._parent_path(self.path_var.get()))
        elif entry["type"] == "dir":
            self._load_dir(self._join_path(self.path_var.get(), entry["name"]))

    def _set_action_status(self, text: str, color: str = COLOR_TEXT_MUTED):
        self.action_status_lbl.config(text=text, fg=color)

    # ============================================================
    #  筛选 KV cache / 查看日志
    # ============================================================

    def _grep_command(self) -> Optional[str]:
        mode = self._source_mode()
        grep = "grep -e 'GPU KV cache size' -e 'Maximum concurrency'"
        if mode == "docker_logs":
            container = self.container_var.get()
            if not container:
                return None
            return f"docker logs {_q(container)} 2>&1 | {grep}"
        if not self.current_file:
            return None
        if mode == "container":
            container = self.container_var.get()
            if not container:
                return None
            return f"docker exec {_q(container)} {grep} {_q(self.current_file)}"
        return f"{grep} {_q(self.current_file)}"

    def _view_command(self) -> Optional[str]:
        mode = self._source_mode()
        if mode == "docker_logs":
            container = self.container_var.get()
            if not container:
                return None
            return f"docker logs --tail {VIEW_DOCKER_LOGS_LINES} {_q(container)} 2>&1"
        if not self.current_file:
            return None
        if mode == "container":
            container = self.container_var.get()
            if not container:
                return None
            return (f"docker exec {_q(container)} "
                    f"tail -c {VIEW_TAIL_BYTES} {_q(self.current_file)}")
        return f"tail -c {VIEW_TAIL_BYTES} {_q(self.current_file)}"

    def _require_ready(self) -> Optional[SSHManager]:
        ssh = self._active_ssh()
        if ssh is None or not ssh.connected:
            showwarning("提示", "请先连接服务器", parent=self.dialog)
            return None
        mode = self._source_mode()
        if mode in ("container", "docker_logs") and not self.container_var.get():
            showwarning("提示", "请先选择容器", parent=self.dialog)
            return None
        if mode != "docker_logs" and not self.current_file:
            showwarning("提示", "请先在列表中选择日志文件",
                                   parent=self.dialog)
            return None
        return ssh

    def _do_grep(self):
        ssh = self._require_ready()
        if ssh is None:
            return
        cmd = self._grep_command()
        if cmd is None:
            showwarning("提示", "无法生成筛选命令, 请检查容器/文件选择",
                                   parent=self.dialog)
            return

        self.grep_btn.config(state=tk.DISABLED)
        self._set_action_status("筛选中...", COLOR_WARNING)

        def work():
            code, out, err = ssh.execute(cmd, timeout=180)

            def done():
                self.grep_btn.config(state=tk.NORMAL)
                self._on_grep_done(cmd, code, out, err)

            self.dialog.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _on_grep_done(self, cmd: str, code: int, out: str, err: str):
        if self.on_command:
            self.on_command(cmd)

        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)

        if code == 0 and out.strip():
            self.result_text.insert("1.0", out.rstrip() + "\n")
            kv, max_len = self._parse_kv_results(out)
            self.parsed_kv = kv
            self.parsed_max_len = max_len

            parts = []
            if kv is not None:
                parts.append(f"单个DP组KV cache = {kv:,} tokens")
            if max_len is not None:
                parts.append(f"模型最大上下文 = {max_len:,} tokens")
            if parts:
                self.parsed_lbl.config(text="  |  ".join(parts), fg=COLOR_SUCCESS)
                self.fill_btn.config(state=tk.NORMAL)
                self._set_action_status("筛选完成, 可一键填入参数", COLOR_SUCCESS)
            else:
                self.parsed_lbl.config(text="未解析到 KV cache / 最大上下文数值",
                                       fg=COLOR_WARNING)
                self.fill_btn.config(state=tk.DISABLED)
                self._set_action_status("有匹配行但未解析出数值", COLOR_WARNING)
        elif code == 1:
            self.result_text.insert("1.0", "(未找到匹配行, 请确认选择的是 vLLM 启动日志)\n")
            self.parsed_lbl.config(text="", fg=COLOR_TEXT_MUTED)
            self.fill_btn.config(state=tk.DISABLED)
            self._set_action_status("未找到匹配行", COLOR_WARNING)
        else:
            msg = err.strip() or out.strip() or f"exit={code}"
            self.result_text.insert("1.0", f"筛选失败:\n{msg}\n")
            self.parsed_lbl.config(text="", fg=COLOR_TEXT_MUTED)
            self.fill_btn.config(state=tk.DISABLED)
            self._set_action_status("筛选失败", COLOR_ERROR)

        self.result_text.config(state=tk.DISABLED)

    @staticmethod
    def _parse_kv_results(text: str) -> Tuple[Optional[int], Optional[int]]:
        """从 grep 结果解析 (单个DP组KV cache tokens, 模型最大上下文 tokens)"""
        kv = None
        max_len = None

        match = re.search(r"GPU KV cache size:?\s*([\d,]+)\s*tokens", text)
        if match:
            try:
                kv = int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        match = re.search(r"Maximum concurrency for ([\d,]+) tokens per request", text)
        if match:
            try:
                max_len = int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        return kv, max_len

    def _fill_params(self):
        filled = []
        if self.parsed_kv is not None and self.kv_cache_var is not None:
            self.kv_cache_var.set(str(self.parsed_kv))
            filled.append(f"单个DP组KV cache={self.parsed_kv:,}")
        if self.parsed_max_len is not None and self.max_req_len_var is not None:
            self.max_req_len_var.set(str(self.parsed_max_len))
            filled.append(f"模型最大上下文={self.parsed_max_len:,}")

        if filled:
            self._set_action_status("已填入: " + "; ".join(filled), COLOR_SUCCESS)
            showinfo("成功", "已填入:\n" + "\n".join(filled),
                                parent=self.dialog)

    def _view_log(self):
        ssh = self._require_ready()
        if ssh is None:
            return
        cmd = self._view_command()
        if cmd is None:
            showwarning("提示", "无法生成查看命令, 请检查容器/文件选择",
                                   parent=self.dialog)
            return

        self.view_btn.config(state=tk.DISABLED)
        self._set_action_status("加载日志中...", COLOR_WARNING)

        def work():
            code, out, err = ssh.execute(cmd, timeout=180)

            def done():
                self.view_btn.config(state=tk.NORMAL)
                if code == 0:
                    self._open_viewer(cmd, out if out.strip() else "(日志为空)")
                    self._set_action_status("日志已加载", COLOR_SUCCESS)
                else:
                    msg = err.strip() or out.strip() or f"exit={code}"
                    lines = msg.splitlines()
                    self._set_action_status(f"查看失败: {lines[-1]}", COLOR_ERROR)

            self.dialog.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _open_viewer(self, source_desc: str, content: str):
        window = tk.Toplevel(self.dialog)
        window.title("日志查看")
        window.geometry("920x600")
        window.configure(bg=COLOR_BG)

        header = tk.Frame(window, bg=COLOR_CARD, bd=1, relief=tk.SOLID)
        header.pack(fill=tk.X)
        LocalizedLabel(header, text="来源命令:", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 8), anchor=tk.W).pack(fill=tk.X, padx=10, pady=(8, 0))
        LocalizedLabel(header, text=source_desc, bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=("Consolas", 8), anchor=tk.W).pack(fill=tk.X, padx=10)
        tail_note = (f"已加载内容: {len(content)} 字符 "
                     f"(文件取尾部 {VIEW_TAIL_BYTES // 1024 // 1024}MB, "
                     f"docker logs 取尾部 {VIEW_DOCKER_LOGS_LINES} 行)")
        LocalizedLabel(header, text=tail_note, bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                 font=("Segoe UI", 8), anchor=tk.W).pack(fill=tk.X, padx=10,
                                                         pady=(0, 8))

        body = tk.Frame(window, bg=COLOR_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        xscroll = tk.Scrollbar(body, orient=tk.HORIZONTAL)
        yscroll = tk.Scrollbar(body, orient=tk.VERTICAL)
        text = tk.Text(body, wrap=tk.NONE, font=("Consolas", 9),
                       bg=COLOR_CARD, fg=COLOR_TEXT, relief=tk.SOLID, bd=1)
        xscroll.config(command=text.xview)
        yscroll.config(command=text.yview)
        text.config(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", content)
        text.config(state=tk.DISABLED)

        buttons = tk.Frame(window, bg=COLOR_BG)
        buttons.pack(fill=tk.X, padx=8, pady=(0, 8))

        def _copy_all():
            window.clipboard_clear()
            window.clipboard_append(content)

        LocalizedButton(buttons, text="复制全部", font=("Segoe UI", 8), relief=tk.FLAT,
                  bg=COLOR_PRIMARY, fg="white", padx=12,
                  command=_copy_all).pack(side=tk.LEFT)
        LocalizedButton(buttons, text="关闭", font=("Segoe UI", 8), relief=tk.FLAT,
                  bg=COLOR_CARD, fg=COLOR_TEXT, padx=12,
                  command=window.destroy).pack(side=tk.RIGHT)
