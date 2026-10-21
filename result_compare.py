"""
结果对比分析 - 加载两个测试结果目录, 按输入规模匹配测试用例并对比指标:
1. 数据源: 目录内 results_*.csv / *.csv, 无CSV时回退解析 test_*.log
2. 匹配: 先按(输入长度,输出长度)精确匹配, 剩余按输入长度回退匹配
3. 输出: 差异表格(A/B/Δ/Δ%) + 每指标分组柱状图(原生Canvas), 支持导出CSV
"""

import csv
import math
import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from typing import Dict, List, Optional, Tuple

from log_parser import CSV_FIELDS


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
CHART_COLOR_A = "#2563eb"
CHART_COLOR_B = "#f59e0b"


# 可对比指标: (字段名, 显示名, 单位, 小数位, 分类)
METRIC_FIELDS = [
    ("TTFT_avg", "TTFT平均", "ms", 2, "TTFT"),
    ("TTFT_min", "TTFT最小", "ms", 2, "TTFT"),
    ("TTFT_max", "TTFT最大", "ms", 2, "TTFT"),
    ("TTFT_P90", "TTFT P90", "ms", 2, "TTFT"),
    ("TPOT_avg", "TPOT平均", "ms", 2, "TPOT"),
    ("TPOT_min", "TPOT最小", "ms", 2, "TPOT"),
    ("TPOT_max", "TPOT最大", "ms", 2, "TPOT"),
    ("TPOT_SLO_P90", "TPOT SLO P90", "ms", 2, "TPOT"),
    ("E2EL_avg", "E2E延迟平均", "ms", 2, "E2E延迟"),
    ("E2EL_min", "E2E延迟最小", "ms", 2, "E2E延迟"),
    ("E2EL_max", "E2E延迟最大", "ms", 2, "E2E延迟"),
    ("E2EL_P90", "E2E延迟P90", "ms", 2, "E2E延迟"),
    ("E2E_throughput", "E2E吞吐", "tok/s", 2, "吞吐"),
    ("output_throughput", "输出吞吐", "tok/s", 2, "吞吐"),
    ("input_token_throughput", "输入吞吐", "tok/s", 2, "吞吐"),
    ("prefill_token_throughput", "预填充吞吐", "tok/s", 2, "吞吐"),
    ("qps", "QPS", "req/s", 2, "吞吐"),
    ("qpm", "QPM", "req/min", 2, "吞吐"),
    ("hbm_hit_rate", "HBM命中率", "%", 1, "命中率"),
    ("external_hit_rate", "外部命中率", "%", 1, "命中率"),
    ("E2E_time", "E2E时间", "s", 2, "其他"),
]

DEFAULT_METRICS = {"TTFT_avg", "TPOT_avg", "output_throughput", "qps",
                   "hbm_hit_rate", "external_hit_rate"}


def _to_float(value) -> Optional[float]:
    """安全转float, 失败返回None"""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _case_key(row: Dict) -> Tuple[Optional[int], Optional[int]]:
    """用例标识: (input_len, output_len)"""
    input_len = _to_float(row.get("input_len"))
    output_len = _to_float(row.get("output_len"))
    return (int(input_len) if input_len is not None else None,
            int(output_len) if output_len is not None else None)


def _sort_key(key: Tuple[Optional[int], Optional[int]]):
    return (key[0] if key[0] is not None else 0,
            key[1] if key[1] is not None else 0)


def format_len(value) -> str:
    """8192 -> 8K, 1048576 -> 1M"""
    num = _to_float(value)
    if num is None:
        return "-"
    num = int(num)
    if num >= 1048576 and num % 1048576 == 0:
        return f"{num // 1048576}M"
    if num >= 1024 and num % 1024 == 0:
        return f"{num // 1024}K"
    return str(num)


def format_value(value, decimals: int = 2) -> str:
    num = _to_float(value)
    if num is None:
        return "-"
    return f"{num:,.{decimals}f}"


def load_result_csv(file_path: str) -> Tuple[List[Dict], Optional[str]]:
    """加载并校验结果CSV: 表头字段必须与工具生成的CSV_FIELDS完全一致

    返回 (rows, error); 成功时error为None
    """
    path = Path(file_path)
    if not path.is_file():
        return [], "文件不存在"

    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            header = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
            missing = [field for field in CSV_FIELDS if field not in header]
            extra = [field for field in header if field not in CSV_FIELDS]
            if missing or extra:
                reasons = []
                if missing:
                    reasons.append(f"缺少字段: {', '.join(missing)}")
                if extra:
                    reasons.append(f"多余字段: {', '.join(extra)}")
                return [], "不是工具生成的结果CSV格式 (" + "; ".join(reasons) + ")"
            rows = []
            for raw in reader:
                row = {k.strip(): v for k, v in raw.items() if k and k.strip()}
                if row:
                    rows.append(row)
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"读取失败: {exc}"

    if not rows:
        return [], "CSV中没有数据行"
    return rows, None


def match_case_rows(rows_a: List[Dict], rows_b: List[Dict]):
    """匹配两组结果行

    第一轮按(input_len, output_len)精确匹配;
    未匹配的行回退按input_len匹配(标注为输入匹配)。
    返回 (matches, unmatched_a, unmatched_b),
    match = {'row_a':..., 'row_b':..., 'exact': bool}
    """
    matches = []
    used_b = [False] * len(rows_b)
    matched_a = [False] * len(rows_a)

    for i, row_a in enumerate(rows_a):
        key_a = _case_key(row_a)
        for j, row_b in enumerate(rows_b):
            if not used_b[j] and _case_key(row_b) == key_a:
                matches.append({"row_a": row_a, "row_b": row_b, "exact": True})
                used_b[j] = True
                matched_a[i] = True
                break

    for i, row_a in enumerate(rows_a):
        if matched_a[i]:
            continue
        input_a = _case_key(row_a)[0]
        for j, row_b in enumerate(rows_b):
            if not used_b[j] and _case_key(row_b)[0] == input_a:
                matches.append({"row_a": row_a, "row_b": row_b, "exact": False})
                used_b[j] = True
                matched_a[i] = True
                break

    matches.sort(key=lambda m: _sort_key(_case_key(m["row_a"])))
    unmatched_a = sum(1 for flag in matched_a if not flag)
    unmatched_b = sum(1 for flag in used_b if not flag)
    return matches, unmatched_a, unmatched_b


def compute_comparison(match: Dict, field: str) -> Dict:
    """计算单个匹配对单个指标的对比值 (A=基准, B=对比)"""
    value_a = _to_float(match["row_a"].get(field))
    value_b = _to_float(match["row_b"].get(field))
    diff = pct = None
    if value_a is not None and value_b is not None:
        diff = value_b - value_a
        if value_a != 0:
            pct = (value_b - value_a) / abs(value_a) * 100
    return {"a": value_a, "b": value_b, "diff": diff, "pct": pct}


def _nice_ceiling(value: float) -> float:
    """向上取整到 1/2/5*10^k 的美观刻度"""
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    if fraction <= 1:
        nice = 1.0
    elif fraction <= 2:
        nice = 2.0
    elif fraction <= 5:
        nice = 5.0
    else:
        nice = 10.0
    return nice * (10 ** exponent)


class BarChartWidget(tk.Canvas):
    """分组柱状图 (A vs B), 原生Canvas绘制, 随窗口宽度自适应重绘"""

    def __init__(self, parent, title: str, labels: List[str],
                 values_a: List[Optional[float]], values_b: List[Optional[float]],
                 name_a: str = "A", name_b: str = "B",
                 unit: str = "", decimals: int = 2, height: int = 250,
                 **kwargs):
        super().__init__(parent, bg=COLOR_CARD, height=height,
                         highlightthickness=1, highlightbackground=COLOR_BORDER,
                         **kwargs)
        self.title = title
        self.labels = labels
        self.values_a = values_a
        self.values_b = values_b
        self.name_a = name_a
        self.name_b = name_b
        self.unit = unit
        self.decimals = decimals
        self._draw_job = None
        self.bind("<Configure>", lambda _event: self._schedule_draw())

    def _schedule_draw(self):
        if self._draw_job is not None:
            self.after_cancel(self._draw_job)
        self._draw_job = self.after(60, self._redraw)

    def _redraw(self):
        self._draw_job = None
        self.delete("all")
        width = max(self.winfo_width(), 120)
        height = max(self.winfo_height(), 120)

        left, right, top, bottom = 78, 16, 34, 62
        plot_w = width - left - right
        plot_h = height - top - bottom
        if plot_w < 40 or plot_h < 40:
            return

        values = [v for v in self.values_a + self.values_b if v is not None]
        if not values:
            self.create_text(width // 2, height // 2, text="无有效数据",
                             fill=COLOR_TEXT_MUTED, font=("Segoe UI", 9))
            return

        y_max = _nice_ceiling(max(values))
        y_min = min(0.0, min(values))
        span = y_max - y_min

        def y_of(value: float) -> float:
            return top + plot_h * (y_max - value) / span

        # 标题
        title_text = f"{self.title} ({self.unit})" if self.unit else self.title
        self.create_text(left + 4, 12, anchor=tk.W, text=title_text,
                         fill=COLOR_TEXT, font=("Segoe UI", 9, "bold"))

        # 网格线与Y轴刻度
        for i in range(5):
            value = y_max - span * i / 4
            y = y_of(value)
            self.create_line(left, y, left + plot_w, y, fill=COLOR_BORDER,
                             dash=(2, 3))
            label = f"{value:,.{self.decimals}g}" if value != int(value) else f"{int(value):,}"
            self.create_text(left - 6, y, anchor=tk.E, text=label,
                             fill=COLOR_TEXT_MUTED, font=("Segoe UI", 7))

        # 基线
        self.create_line(left, top + plot_h, left + plot_w, top + plot_h,
                         fill=COLOR_TEXT)

        # 柱状
        count = max(len(self.labels), 1)
        group_w = plot_w / count
        bar_w = min(group_w * 0.30, 54)
        show_value_labels = count <= 14

        for index, label in enumerate(self.labels):
            center = left + group_w * (index + 0.5)
            for values, offset, color in ((self.values_a, -1, CHART_COLOR_A),
                                          (self.values_b, 1, CHART_COLOR_B)):
                value = values[index] if index < len(values) else None
                if value is None:
                    continue
                x0 = center + offset * bar_w * 0.55 - bar_w / 2
                x1 = x0 + bar_w
                y_top = y_of(value)
                y_base = y_of(max(0, y_min))
                self.create_rectangle(x0, y_top, x1, y_base, fill=color,
                                      outline="")
                if show_value_labels:
                    text = f"{value:,.{self.decimals}f}"
                    self.create_text((x0 + x1) / 2, y_top - 8, text=text,
                                     fill=COLOR_TEXT_MUTED, font=("Segoe UI", 7))

            self.create_text(center, top + plot_h + 6, text=label,
                             anchor=tk.N, justify=tk.CENTER,
                             fill=COLOR_TEXT, font=("Segoe UI", 7))

        # 图例 (右上角)
        legend_x = left + plot_w - 150
        self.create_rectangle(legend_x, 8, legend_x + 12, 20, fill=CHART_COLOR_A,
                              outline="")
        self.create_text(legend_x + 16, 14, anchor=tk.W, text=self.name_a,
                         fill=COLOR_TEXT_MUTED, font=("Segoe UI", 7))
        self.create_rectangle(legend_x + 76, 8, legend_x + 88, 20,
                              fill=CHART_COLOR_B, outline="")
        self.create_text(legend_x + 92, 14, anchor=tk.W, text=self.name_b,
                         fill=COLOR_TEXT_MUTED, font=("Segoe UI", 7))


class ResultCompareDialog:
    """结果对比分析对话框: 选择两个测试结果目录, 按输入规模匹配并对比指标"""

    def __init__(self, parent: tk.Misc):
        self.parent = parent
        self.rows_a: List[Dict] = []
        self.rows_b: List[Dict] = []
        self.matches: List[Dict] = []
        self.match_vars: List[tk.BooleanVar] = []
        self.metric_vars: List[tk.BooleanVar] = []
        self.compared: bool = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("结果对比分析")
        self.dialog.geometry("1080x780")
        self.dialog.minsize(900, 640)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.configure(bg=COLOR_BG)

        self._build_ui()

    # ============================================================
    #  UI 构建
    # ============================================================

    def _build_ui(self):
        self._build_dir_section()

        # 中部: 匹配用例 + 指标选择 (左右分栏)
        middle = tk.Frame(self.dialog, bg=COLOR_BG)
        middle.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(0, weight=1)

        self._build_cases_section(middle)
        self._build_metrics_section(middle)
        self._build_results_section()

    def _build_dir_section(self):
        box = tk.LabelFrame(self.dialog, text=" 结果CSV文件 (工具生成, 格式自动校验) ",
                            bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.pack(fill=tk.X, padx=10, pady=(10, 4))

        row_a = tk.Frame(box, bg=COLOR_CARD)
        row_a.pack(fill=tk.X, padx=10, pady=(8, 2))
        tk.Label(row_a, text="文件A (基准):", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=("Segoe UI", 9), width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.file_a_var = tk.StringVar()
        tk.Entry(row_a, textvariable=self.file_a_var, font=("Segoe UI", 9)
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        tk.Button(row_a, text="选择CSV...", font=("Segoe UI", 8),
                  command=lambda: self._browse_csv(self.file_a_var)
                  ).pack(side=tk.LEFT, padx=4)

        row_b = tk.Frame(box, bg=COLOR_CARD)
        row_b.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row_b, text="文件B (对比):", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=("Segoe UI", 9), width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.file_b_var = tk.StringVar()
        tk.Entry(row_b, textvariable=self.file_b_var, font=("Segoe UI", 9)
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        tk.Button(row_b, text="选择CSV...", font=("Segoe UI", 8),
                  command=lambda: self._browse_csv(self.file_b_var)
                  ).pack(side=tk.LEFT, padx=4)

        action_row = tk.Frame(box, bg=COLOR_CARD)
        action_row.pack(fill=tk.X, padx=10, pady=(2, 8))
        tk.Button(action_row, text="加载数据", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white", padx=14,
                  command=self._load_data).pack(side=tk.LEFT)
        self.load_status_lbl = tk.Label(action_row, text="选择两个工具生成的 results_*.csv 文件",
                                        bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                        font=("Segoe UI", 8))
        self.load_status_lbl.pack(side=tk.LEFT, padx=10)

    def _build_cases_section(self, parent):
        box = tk.LabelFrame(parent, text=" 匹配的测试用例 (勾选参与对比) ",
                            bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))

        select_row = tk.Frame(box, bg=COLOR_CARD)
        select_row.pack(fill=tk.X, padx=8, pady=(6, 2))
        tk.Button(select_row, text="全选", font=("Segoe UI", 7), relief=tk.FLAT,
                  bg=COLOR_BORDER, padx=8,
                  command=lambda: self._toggle_all_matches(True)).pack(side=tk.LEFT)
        tk.Button(select_row, text="全不选", font=("Segoe UI", 7), relief=tk.FLAT,
                  bg=COLOR_BORDER, padx=8,
                  command=lambda: self._toggle_all_matches(False)).pack(side=tk.LEFT,
                                                                      padx=4)
        self.match_count_lbl = tk.Label(select_row, text="(加载数据后显示)",
                                        bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                                        font=("Segoe UI", 8))
        self.match_count_lbl.pack(side=tk.LEFT, padx=8)

        self.cases_canvas = tk.Canvas(box, bg=COLOR_CARD, height=130,
                                      highlightthickness=0)
        cases_scroll = tk.Scrollbar(box, orient=tk.VERTICAL,
                                    command=self.cases_canvas.yview)
        self.cases_inner = tk.Frame(self.cases_canvas, bg=COLOR_CARD)
        self.cases_inner.bind(
            "<Configure>",
            lambda _e: self.cases_canvas.configure(
                scrollregion=self.cases_canvas.bbox("all")))
        self.cases_canvas.create_window((0, 0), window=self.cases_inner,
                                        anchor=tk.NW)
        self.cases_canvas.configure(yscrollcommand=cases_scroll.set)
        self.cases_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                               padx=(8, 0), pady=(2, 8))
        cases_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8))
        self.cases_canvas.bind(
            "<Enter>", lambda _e: self.cases_canvas.bind_all(
                "<MouseWheel>", lambda ev: self.cases_canvas.yview_scroll(
                    int(-1 * (ev.delta / 120)), "units")))
        self.cases_canvas.bind(
            "<Leave>", lambda _e: self.cases_canvas.unbind_all("<MouseWheel>"))

    def _build_metrics_section(self, parent):
        box = tk.LabelFrame(parent, text=" 对比指标 (勾选要观察的指标) ",
                            bg=COLOR_CARD, fg=COLOR_TEXT,
                            font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID)
        box.grid(row=0, column=1, sticky=tk.NSEW, padx=(5, 0))

        self.metrics_canvas = tk.Canvas(box, bg=COLOR_CARD, height=130,
                                        highlightthickness=0)
        metrics_scroll = tk.Scrollbar(box, orient=tk.VERTICAL,
                                      command=self.metrics_canvas.yview)
        self.metrics_inner = tk.Frame(self.metrics_canvas, bg=COLOR_CARD)
        self.metrics_inner.bind(
            "<Configure>",
            lambda _e: self.metrics_canvas.configure(
                scrollregion=self.metrics_canvas.bbox("all")))
        self.metrics_canvas.create_window((0, 0), window=self.metrics_inner,
                                          anchor=tk.NW)
        self.metrics_canvas.configure(yscrollcommand=metrics_scroll.set)
        self.metrics_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                 padx=(8, 0), pady=(6, 8))
        metrics_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=6)
        self.metrics_canvas.bind(
            "<Enter>", lambda _e: self.metrics_canvas.bind_all(
                "<MouseWheel>", lambda ev: self.metrics_canvas.yview_scroll(
                    int(-1 * (ev.delta / 120)), "units")))
        self.metrics_canvas.bind(
            "<Leave>", lambda _e: self.metrics_canvas.unbind_all("<MouseWheel>"))

        # 按类别分组展示指标
        categories = []
        for field, name, unit, _decimals, category in METRIC_FIELDS:
            if category not in categories:
                categories.append(category)

        self.metric_vars = []
        for category in categories:
            tk.Label(self.metrics_inner, text=f"■ {category}", bg=COLOR_CARD,
                     fg=COLOR_PRIMARY, font=("Segoe UI", 8, "bold"),
                     anchor=tk.W).pack(fill=tk.X, pady=(6, 1))
            for field, name, unit, _decimals, cat in METRIC_FIELDS:
                if cat != category:
                    continue
                var = tk.BooleanVar(value=field in DEFAULT_METRICS)
                self.metric_vars.append(var)
                text = f"{name} ({unit})" if unit else name
                tk.Checkbutton(self.metrics_inner, text=text, variable=var,
                               bg=COLOR_CARD, fg=COLOR_TEXT,
                               font=("Segoe UI", 8), anchor=tk.W
                               ).pack(fill=tk.X, padx=(14, 0))

    def _build_results_section(self):
        # 操作按钮
        action_row = tk.Frame(self.dialog, bg=COLOR_BG)
        action_row.pack(fill=tk.X, padx=10, pady=(6, 4))
        tk.Button(action_row, text="开始对比", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, bg=COLOR_PRIMARY, fg="white", padx=16,
                  command=self._do_compare).pack(side=tk.LEFT)
        self.export_btn = tk.Button(action_row, text="导出对比CSV",
                                    font=("Segoe UI", 9), relief=tk.FLAT,
                                    bg=COLOR_CARD, fg=COLOR_PRIMARY, padx=12,
                                    state=tk.DISABLED,
                                    command=self._export_csv)
        self.export_btn.pack(side=tk.LEFT, padx=8)
        self.compare_status_lbl = tk.Label(action_row, text="", bg=COLOR_BG,
                                           fg=COLOR_TEXT_MUTED,
                                           font=("Segoe UI", 8))
        self.compare_status_lbl.pack(side=tk.LEFT, padx=10)
        tk.Button(action_row, text="关闭", font=("Segoe UI", 9), relief=tk.FLAT,
                  bg=COLOR_CARD, fg=COLOR_TEXT, padx=12,
                  command=self.dialog.destroy).pack(side=tk.RIGHT)

        # 上下分割: 对比表格 / 柱状图
        self.paned = ttk.PanedWindow(self.dialog, orient=tk.VERTICAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        table_pane = tk.Frame(self.paned, bg=COLOR_BG)
        self.paned.add(table_pane, weight=3)
        tk.Label(table_pane, text="差异对比表 (Δ = B - A):", bg=COLOR_BG,
                 fg=COLOR_TEXT, font=("Segoe UI", 9, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        self.table_container = tk.Frame(table_pane, bg=COLOR_BG)
        self.table_container.pack(fill=tk.BOTH, expand=True)

        chart_pane = tk.Frame(self.paned, bg=COLOR_BG)
        self.paned.add(chart_pane, weight=4)
        tk.Label(chart_pane, text="柱状对比图 (每个指标一张, A蓝/B橙):",
                 bg=COLOR_BG, fg=COLOR_TEXT, font=("Segoe UI", 9, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(4, 4))

        self.charts_canvas = tk.Canvas(chart_pane, bg=COLOR_BG,
                                       highlightthickness=0)
        charts_scroll = tk.Scrollbar(chart_pane, orient=tk.VERTICAL,
                                     command=self.charts_canvas.yview)
        self.charts_inner = tk.Frame(self.charts_canvas, bg=COLOR_BG)
        self.charts_inner.bind(
            "<Configure>",
            lambda _e: self.charts_canvas.configure(
                scrollregion=self.charts_canvas.bbox("all")))
        self.charts_window = self.charts_canvas.create_window(
            (0, 0), window=self.charts_inner, anchor=tk.NW)
        self.charts_canvas.configure(yscrollcommand=charts_scroll.set)
        self.charts_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                pady=(0, 0))
        charts_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.charts_canvas.bind(
            "<Configure>",
            lambda _e: self.charts_canvas.itemconfigure(
                self.charts_window, width=self.charts_canvas.winfo_width()))
        self.charts_canvas.bind(
            "<Enter>", lambda _e: self.charts_canvas.bind_all(
                "<MouseWheel>", lambda ev: self.charts_canvas.yview_scroll(
                    int(-1 * (ev.delta / 120)), "units")))
        self.charts_canvas.bind(
            "<Leave>", lambda _e: self.charts_canvas.unbind_all("<MouseWheel>"))

    # ============================================================
    #  数据加载 / 匹配
    # ============================================================

    def _browse_csv(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            parent=self.dialog, title="选择结果CSV文件",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")])
        if path:
            var.set(path)

    def _toggle_all_matches(self, enabled: bool):
        for var in self.match_vars:
            var.set(enabled)

    def _load_data(self):
        file_a = self.file_a_var.get().strip()
        file_b = self.file_b_var.get().strip()
        if not file_a or not file_b:
            messagebox.showwarning("提示", "请先选择文件A和文件B", parent=self.dialog)
            return
        if not os.path.isfile(file_a) or not os.path.isfile(file_b):
            messagebox.showwarning("提示", "文件不存在, 请检查路径", parent=self.dialog)
            return
        if os.path.normpath(file_a) == os.path.normpath(file_b):
            messagebox.showwarning("提示", "文件A和文件B相同, 请选择两个不同的结果CSV",
                                   parent=self.dialog)
            return

        self.rows_a, error_a = load_result_csv(file_a)
        self.rows_b, error_b = load_result_csv(file_b)

        errors = []
        if error_a:
            errors.append(f"文件A: {error_a}")
        if error_b:
            errors.append(f"文件B: {error_b}")
        if errors:
            messagebox.showwarning("格式校验失败", "\n".join(errors),
                                   parent=self.dialog)
            self._set_load_status("CSV格式校验失败", COLOR_ERROR)
            return

        self.matches, unmatched_a, unmatched_b = match_case_rows(self.rows_a,
                                                                 self.rows_b)
        self._populate_matches()

        exact_count = sum(1 for m in self.matches if m["exact"])
        input_only = len(self.matches) - exact_count
        summary = (f"A: {len(self.rows_a)}条  B: {len(self.rows_b)}条  |  "
                   f"匹配 {len(self.matches)} 对 (精确 {exact_count} / "
                   f"输入 {input_only})")
        if unmatched_a or unmatched_b:
            summary += f"  |  未匹配: A余 {unmatched_a}, B余 {unmatched_b}"
        self._set_load_status(summary, COLOR_SUCCESS if self.matches
                              else COLOR_WARNING)

        if not self.matches:
            messagebox.showwarning("提示", "两个目录中没有找到输入规模相同的测试用例",
                                   parent=self.dialog)

    def _populate_matches(self):
        for child in self.cases_inner.winfo_children():
            child.destroy()
        self.match_vars = []

        for index, match in enumerate(self.matches, 1):
            key_a = _case_key(match["row_a"])
            key_b = _case_key(match["row_b"])
            var = tk.BooleanVar(value=True)
            self.match_vars.append(var)

            match_text = "精确" if match["exact"] else "输入"
            output_text = (format_len(key_a[1]) if match["exact"]
                           else f"A:{format_len(key_a[1])} B:{format_len(key_b[1])}")
            req_a = format_value(match["row_a"].get("total_req"), 0)
            req_b = format_value(match["row_b"].get("total_req"), 0)
            cc_a = format_value(match["row_a"].get("max_cc"), 0)
            cc_b = format_value(match["row_b"].get("max_cc"), 0)
            label = (f"{index}. 输入 {format_len(key_a[0])}  输出 {output_text}"
                     f"  [{match_text}]  req {req_a}/{req_b}"
                     f"  max_cc {cc_a}/{cc_b}")
            tk.Checkbutton(self.cases_inner, text=label, variable=var,
                           bg=COLOR_CARD, fg=COLOR_TEXT, anchor=tk.W,
                           font=("Segoe UI", 8)).pack(fill=tk.X, pady=1)

        self.match_count_lbl.config(
            text=f"共 {len(self.matches)} 对"
                 if self.matches else "(无匹配用例)")

    def _set_load_status(self, text: str, color: str = COLOR_TEXT_MUTED):
        self.load_status_lbl.config(text=text, fg=color)

    # ============================================================
    #  对比执行
    # ============================================================

    def _selected_metrics(self) -> List[Tuple[str, str, str, int]]:
        return [(field, name, unit, decimals)
                for (field, name, unit, decimals, _cat), var
                in zip(METRIC_FIELDS, self.metric_vars) if var.get()]

    def _selected_matches(self) -> List[Dict]:
        return [match for match, var in zip(self.matches, self.match_vars)
                if var.get()]

    def _do_compare(self):
        selected_matches = self._selected_matches()
        selected_metrics = self._selected_metrics()

        if not self.matches:
            messagebox.showwarning("提示", "请先加载数据", parent=self.dialog)
            return
        if not selected_matches:
            messagebox.showwarning("提示", "请至少勾选一个匹配的测试用例",
                                   parent=self.dialog)
            return
        if not selected_metrics:
            messagebox.showwarning("提示", "请至少勾选一个对比指标",
                                   parent=self.dialog)
            return

        self._build_table(selected_matches, selected_metrics)
        self._build_charts(selected_matches, selected_metrics)
        self.compared = True
        self.export_btn.config(state=tk.NORMAL)
        self.compare_status_lbl.config(
            text=f"已对比 {len(selected_matches)} 个用例 × {len(selected_metrics)} 个指标",
            fg=COLOR_SUCCESS)

    def _build_table(self, selected_matches: List[Dict],
                     selected_metrics: List[Tuple[str, str, str, int]]):
        for child in self.table_container.winfo_children():
            child.destroy()

        columns = ["match", "input", "output", "req", "max_cc"]
        headings = [("匹配", 52), ("Input", 70), ("Output", 76),
                    ("Req A/B", 86), ("Max_CC A/B", 96)]
        for field, name, _unit, _decimals in selected_metrics:
            columns.extend([f"{field}_a", f"{field}_b",
                            f"{field}_diff", f"{field}_pct"])
            headings.extend([(f"{name} A", 82), (f"{name} B", 82),
                             (f"{name} Δ", 82), (f"{name} Δ%", 68)])

        frame = tk.Frame(self.table_container, bg=COLOR_BG)
        frame.pack(fill=tk.BOTH, expand=True)

        tree = ttk.Treeview(frame, columns=columns, show="headings",
                            selectmode="browse")
        for column, (title, width) in zip(columns, headings):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor=tk.CENTER, stretch=False)

        vsb = tk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        hsb = tk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.config(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.compare_rows = []
        for match in selected_matches:
            key_a = _case_key(match["row_a"])
            key_b = _case_key(match["row_b"])
            values = ["精确" if match["exact"] else "输入",
                      format_len(key_a[0])]
            if match["exact"]:
                values.append(format_len(key_a[1]))
            else:
                values.append(f"{format_len(key_a[1])}/{format_len(key_b[1])}")
            req_a = format_value(match["row_a"].get("total_req"), 0)
            req_b = format_value(match["row_b"].get("total_req"), 0)
            cc_a = format_value(match["row_a"].get("max_cc"), 0)
            cc_b = format_value(match["row_b"].get("max_cc"), 0)
            values.append(f"{req_a}/{req_b}")
            values.append(f"{cc_a}/{cc_b}")

            row_record = {"match": values[0], "input": values[1],
                          "output": values[2], "Req A/B": values[3],
                          "Max_CC A/B": values[4]}
            for field, name, _unit, decimals in selected_metrics:
                result = compute_comparison(match, field)
                values.extend([
                    format_value(result["a"], decimals),
                    format_value(result["b"], decimals),
                    (f"{result['diff']:+,.{decimals}f}"
                     if result["diff"] is not None else "-"),
                    (f"{result['pct']:+.1f}%"
                     if result["pct"] is not None else "-"),
                ])
                row_record[f"{name} A"] = values[-4]
                row_record[f"{name} B"] = values[-3]
                row_record[f"{name} Δ"] = values[-2]
                row_record[f"{name} Δ%"] = values[-1]

            self.compare_rows.append(row_record)
            tree.insert("", tk.END, values=values)

        self.compare_tree = tree
        self.compare_metrics = [name for _f, name, _u, _d in selected_metrics]

    def _build_charts(self, selected_matches: List[Dict],
                      selected_metrics: List[Tuple[str, str, str, int]]):
        for child in self.charts_inner.winfo_children():
            child.destroy()

        name_a = (os.path.splitext(os.path.basename(
            self.file_a_var.get().strip()))[0]) or "A"
        name_b = (os.path.splitext(os.path.basename(
            self.file_b_var.get().strip()))[0]) or "B"

        for field, name, unit, decimals in selected_metrics:
            labels = []
            values_a = []
            values_b = []
            for match in selected_matches:
                labels.append(self._chart_label(match))
                result = compute_comparison(match, field)
                values_a.append(result["a"])
                values_b.append(result["b"])

            chart = BarChartWidget(self.charts_inner, title=name, labels=labels,
                                   values_a=values_a, values_b=values_b,
                                   name_a=f"A: {name_a}", name_b=f"B: {name_b}",
                                   unit=unit, decimals=decimals)
            chart.pack(fill=tk.X, padx=2, pady=6)

    @staticmethod
    def _chart_label(match: Dict) -> str:
        """柱状图横坐标: 输入/输出 + 请求数 + Max_CC (两侧不同用 A↔B 标注)"""
        row_a = match["row_a"]
        row_b = match["row_b"]
        input_len = format_len(row_a.get("input_len"))
        out_a = format_len(row_a.get("output_len"))
        out_b = format_len(row_b.get("output_len"))
        line1 = (f"{input_len}/{out_a}" if out_a == out_b
                 else f"{input_len} {out_a}↔{out_b}")

        req_a = format_value(row_a.get("total_req"), 0)
        req_b = format_value(row_b.get("total_req"), 0)
        cc_a = format_value(row_a.get("max_cc"), 0)
        cc_b = format_value(row_b.get("max_cc"), 0)
        req_part = req_a if req_a == req_b else f"{req_a}↔{req_b}"
        cc_part = cc_a if cc_a == cc_b else f"{cc_a}↔{cc_b}"
        return f"{line1}\nr{req_part} c{cc_part}"

    def _export_csv(self):
        if not getattr(self, "compare_rows", None):
            messagebox.showwarning("提示", "请先执行对比", parent=self.dialog)
            return

        default_name = f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            parent=self.dialog, title="保存对比结果CSV",
            defaultextension=".csv", initialfile=default_name,
            filetypes=[("CSV文件", "*.csv")])
        if not path:
            return

        fieldnames = ["match", "input", "output", "Req A/B", "Max_CC A/B"]
        for metric in self.compare_metrics:
            fieldnames.extend([f"{metric} A", f"{metric} B",
                               f"{metric} Δ", f"{metric} Δ%"])

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.compare_rows)
        except OSError as exc:
            messagebox.showerror("错误", f"导出失败: {exc}", parent=self.dialog)
            return

        self.compare_status_lbl.config(text=f"已导出: {path}", fg=COLOR_SUCCESS)
