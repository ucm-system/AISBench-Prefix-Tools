#!/usr/bin/env python3
"""Lightweight localization layer for the Tk UI."""

import tkinter as tk
from tkinter import ttk, messagebox


SUPPORTED_LANGUAGES = {
    "zh": "中文",
    "en": "English",
}

CURRENT_LANGUAGE = "zh"


TRANSLATIONS = {
    "en": {
        "SSH连接": "SSH Connection",
        "Docker部署": "Docker Deployment",
        "配置文件": "Configuration",
        "测试用例": "Test Cases",
        "执行测试": "Run Tests",
        "1. SSH连接": "1. SSH Connection",
        "2. Docker部署": "2. Docker Deployment",
        "3. 配置文件": "3. Configuration",
        "4. 测试用例": "4. Test Cases",
        "5. 执行测试": "5. Run Tests",
        "AISBench 镜像来源:": "AISBench image source:",
        "API Key (鉴权, 可选):": "API Key (auth, optional):",
        "Docker 部署": "Docker Deployment",
        "GPU KV cache size → 单个DP组KV cache (tokens);   Maximum concurrency → 模型最大上下文 (tokens)":
            "GPU KV cache size → KV cache per DP group (tokens); Maximum concurrency → model max context (tokens)",
        "config.py 位置: 尚未部署": "config.py location: not deployed yet",
        "config.py 位置: 尚未部署（请先完成Docker部署）":
            "config.py location: not deployed yet (finish Docker deployment first)",
        "vLLM服务 IP:": "vLLM service IP:",
        "vLLM服务端口:": "vLLM service port:",
        "● 已连接": "● Connected",
        "● 未连接": "● Not connected",
        "⚠ 已写入但存在不一致!": "⚠ Written but inconsistent!",
        "⚠ 已存在且有内容": "⚠ Exists and is not empty",
        "⚠ 界面与容器配置不一致": "⚠ UI and container config differ",
        "✓ 已写入 (回读失败，请手动验证)": "✓ Written (read-back failed, verify manually)",
        "✓ 配置已保存并验证一致": "✓ Config saved and verified",
        "✓ 验证通过，界面与容器配置一致": "✓ Verified, UI and container config match",
        "✗ 保存失败": "✗ Save failed",
        "✗ 无法读取容器内config.py": "✗ Cannot read config.py from container",
        "上传本地镜像tar包": "Upload local image tar",
        "下一步 >": "Next >",
        "不存在(将创建)": "Does not exist (will create)",
        "临时部署目录:": "Temporary deploy directory:",
        "仅部署期间暂存镜像tar/测试代码，代码导入容器后自动删除，不保留在宿主机":
            "Only stages image tar/test code during deployment; after importing into the container it is removed from the host",
        "从日志自动获取 / 查看日志": "Auto-fetch from logs / view logs",
        "代码下载链接": "Code download link",
        "保存配置到容器": "Save config to container",
        "保持现状": "Keep current state",
        "全选": "Select all",
        "关闭": "Close",
        "内置代码包": "Built-in code package",
        "删除用例": "Delete case",
        "刷新": "Refresh",
        "刷新命令": "Refresh command",
        "前往": "Go",
        "取消": "Cancel",
        "取消全选": "Clear selection",
        "同时删除临时部署目录残留文件": "Also delete temporary deploy directory leftovers",
        "复制": "Copy",
        "复制用例": "Copy case",
        "完成": "Finish",
        "密码": "Password",
        "尚未查询": "Not queried yet",
        "已复制": "Copied",
        "已存在(空)": "Exists (empty)",
        "已有镜像直接复用；代码先暂存宿主机，容器创建后导入容器并自动删除暂存目录":
            "Reuse existing images; code is staged on the host, imported into the container, and the staging directory is removed",
        "已清理": "Cleaned",
        "开始部署": "Start deployment",
        "或密钥文件路径": "or key file path",
        "执行中...": "Running...",
        "执行日志:": "Execution log:",
        "执行机已有镜像": "Use image on execution host",
        "执行测试 → 生成CSV": "Run tests → generate CSV",
        "扫描失败(可稍后重试)": "Scan failed (retry later)",
        "无残留容器": "No residual containers",
        "无需连接服务器": "No server connection required",
        "未发现可用镜像，请上传本地AISBench镜像tar包。":
            "No usable image found. Upload a local AISBench image tar package.",
        "未扫描": "Not scanned",
        "本地zip包": "Local zip package",
        "本地结果保存目录:": "Local result directory:",
        "本工具创建的容器 (aisbench-test-*)": "Containers created by this tool (aisbench-test-*)",
        "查看已有镜像": "View existing images",
        "查询方式:": "Query mode:",
        "检查目录": "Check directory",
        "模型名称 (--served-model-name):": "Model name (--served-model-name):",
        "模型权重路径 (远程主机):": "Model weights path (remote host):",
        "正在刷新...": "Refreshing...",
        "正在扫描残留容器...": "Scanning residual containers...",
        "正在查询执行机镜像...": "Querying execution host images...",
        "正在连接...": "Connecting...",
        "测试代码来源:": "Test code source:",
        "测试用例 (双击单元格可编辑 Input/Output/请求数/并发数):":
            "Test cases (double-click cells to edit Input/Output/request count/concurrency):",
        "测试连接": "Test connection",
        "浏览...": "Browse...",
        "浏览远程目录": "Browse remote directory",
        "添加用例": "Add case",
        "清理中...": "Cleaning...",
        "清理失败": "Cleanup failed",
        "清理残留容器": "Clean residual containers",
        "清理环境": "Clean environment",
        "清理目录": "Clean directory",
        "清理选中": "Clean selected",
        "点击行切换勾选，可清理上次退出时未删除的容器；仅显示本工具创建的容器":
            "Click rows to toggle selection; clean containers left from previous runs. Only containers created by this tool are shown.",
        "生成测试用例": "Generate test cases",
        "生成的测试命令:": "Generated test command:",
        "目录不存在，无需清理": "Directory does not exist; nothing to clean",
        "确认": "Confirm",
        "程序内置": "Built-in",
        "结果对比分析": "Result comparison",
        "结果摘要:": "Result summary:",
        "计算公式:": "Formula:",
        "计算明细 (代入当前KV参数):": "Calculation details (current KV parameters):",
        "请选择执行机上的镜像": "Select an image on the execution host",
        "路径:": "Path:",
        "输入长度 (需小于模型最大上下文):": "Input length (must be below model max context):",
        "输出长度:": "Output length:",
        "连接中...": "Connecting...",
        "选择AISBench镜像包": "Select AISBench image package",
        "选择SSH密钥文件": "Select SSH key file",
        "选择代码zip包": "Select code zip package",
        "选择当前目录": "Select current directory",
        "选择本地结果保存目录": "Select local result directory",
        "部署中...": "Deploying...",
        "部署后已自动清理": "Automatically cleaned after deployment",
        "部署日志:": "Deployment log:",
        "配置预览 (内存中):": "Config preview (in memory):",
        "重新部署": "Redeploy",
        "镜像下载链接": "Image download link",
        "验证配置(读取容器)": "Verify config (read from container)",
        "📊 结果对比分析": "📊 Result comparison",
        "< 上一步": "< Previous",
        "下一步": "Next",
        "语言 / Language:": "Language / Language:",
        "步骤 1: SSH连接到执行机": "Step 1: Connect to execution host via SSH",
        "输入远程执行机的SSH连接信息": "Enter SSH connection information for the remote execution host",
        "执行机 IP *": "Execution host IP *",
        "SSH 端口": "SSH port",
        "用户名 *": "Username *",
        "步骤 2: Docker部署与模型配置": "Step 2: Docker deployment and model configuration",
        "选择执行机已有AISBench镜像或上传tar包, 配置模型/vLLM服务后一键部署容器":
            "Select an existing AISBench image on the execution host or upload a tar package; configure model/vLLM service and deploy the container in one click",
        "aisbench_auto_tools_prefix (程序内置, 部署时自动上传)":
            "aisbench_auto_tools_prefix (built-in, uploaded automatically during deployment)",
        "镜像:": "Image:",
        "代码包:": "Code package:",
        "模型路径:": "Model path:",
        "容器名称:": "Container name:",
        "镜像名称:": "Image name:",
        "步骤 3: 配置 config.py": "Step 3: Configure config.py",
        "配置aisbench_auto_tools_prefix的测试参数": "Configure aisbench_auto_tools_prefix test parameters",
        "* MODEL_NAME (模型名称)": "* MODEL_NAME (model name)",
        "* MODEL_PATH (模型路径)": "* MODEL_PATH (model path)",
        "* HOST_IP (vLLM服务IP)": "* HOST_IP (vLLM service IP)",
        "* HOST_PORT (vLLM服务端口)": "* HOST_PORT (vLLM service port)",
        "  API_KEY (鉴权, 可空)": "  API_KEY (auth, optional)",
        "  DATASET_PATH (自动设置)": "  DATASET_PATH (set automatically)",
        "  WORK_PATH (工作路径)": "  WORK_PATH (working path)",
        "  OUTPUT_DIR (输出路径)": "  OUTPUT_DIR (output path)",
        "  POD_INFO (多DP必填, 格式: ip:port,ip:port)":
            "  POD_INFO (required for multi-DP, format: ip:port,ip:port)",
        "步骤 4: 设计测试用例": "Step 4: Design test cases",
        "根据KV cache信息生成测试参数": "Generate test parameters from KV cache information",
        "  并发数 = floor( total_kv_cache / (input_len + output_len) )":
            "  Concurrency = floor(total_kv_cache / (input_len + output_len))",
        "  最小请求数 = floor(total_kv_cache / input_len / repeat_rate) + 1":
            "  Minimum requests = floor(total_kv_cache / input_len / repeat_rate) + 1",
        "  推荐请求数 = 最小请求数 × 2": "  Recommended requests = minimum requests × 2",
        "  KV使用率 = 并发数 × (input_len + output_len) / total_kv_cache × 100%":
            "  KV usage = concurrency × (input_len + output_len) / total_kv_cache × 100%",
        "单个DP组KV cache (tokens):": "KV cache per DP group (tokens):",
        "DP组数:": "DP groups:",
        "模型最大上下文 (tokens):": "Model max context (tokens):",
        "前缀命中率 (0-1):": "Prefix hit rate (0-1):",
        "请求发送速率 (0=Burst):": "Request send rate (0=Burst):",
        "(选择服务器/容器日志, 筛选结果可一键填入)":
            "(Select server/container logs; filtered results can be filled in with one click)",
        "步骤 5: 执行测试": "Step 5: Run tests",
        "生成.sh脚本 → 容器内执行 → 下载日志 → 解析结果CSV":
            "Generate .sh script → execute in container → download logs → parse result CSV",
        "(测试完成后显示结果摘要)": "(Result summary is displayed after tests finish)",
        " 文件浏览 (双击进入目录, 单击选择文件) ":
            " File browser (double-click to enter a directory, single-click to select a file) ",
        " 日志来源 ": " Log source ",
        " 服务器 ": " Server ",
        " 筛选结果 ": " Filtered result ",
        "其他服务器": "Other server",
        "刷新容器列表": "Refresh container list",
        "填入参数": "Fill parameters",
        "复制全部": "Copy all",
        "容器:": "Container:",
        "密码:": "Password:",
        "密钥:": "Key:",
        "当前文件: (未选择)": "Current file: (not selected)",
        "当前文件: docker logs 输出 (无需选择文件)":
            "Current file: docker logs output (no file selection needed)",
        "未解析到 KV cache / 最大上下文数值": "No KV cache / max context values parsed",
        "未连接": "Not connected",
        "来源命令:": "Source command:",
        "查看日志": "View log",
        "浏览": "Browse",
        "筛选 KV cache": "Filter KV cache",
        "连接": "Connect",
        "连接中...": "Connecting...",
        "选择密钥文件": "Select key file",
        " 匹配的测试用例 (勾选参与对比) ": " Matched test cases (check to include in comparison) ",
        " 对比指标 (勾选要观察的指标) ": " Comparison metrics (check metrics to observe) ",
        " 结果CSV文件 (工具生成, 格式自动校验) ": " Result CSV files (generated by this tool, format validated automatically) ",
        "(加载数据后显示)": "(Displayed after data is loaded)",
        "保存对比结果CSV": "Save comparison result CSV",
        "全不选": "Select none",
        "加载数据": "Load data",
        "导出对比CSV": "Export comparison CSV",
        "差异对比表 (Δ = B - A):": "Difference table (Δ = B - A):",
        "开始对比": "Start comparison",
        "文件A (基准):": "File A (baseline):",
        "文件B (对比):": "File B (comparison):",
        "无有效数据": "No valid data",
        "柱状对比图 (每个指标一张, A蓝/B橙):":
            "Bar charts (one per metric, A blue / B orange):",
        "选择CSV...": "Select CSV...",
        "选择两个工具生成的 results_*.csv 文件": "Select two results_*.csv files generated by this tool",
        "选择结果CSV文件": "Select result CSV file",
    }
}


def set_language(language: str) -> None:
    """Set the active UI language."""
    global CURRENT_LANGUAGE
    if language not in SUPPORTED_LANGUAGES:
        language = "zh"
    CURRENT_LANGUAGE = language


def get_language() -> str:
    """Return the active UI language code."""
    return CURRENT_LANGUAGE


def tr(text: str) -> str:
    """Translate static UI text when possible."""
    if CURRENT_LANGUAGE == "zh":
        return text
    return TRANSLATIONS["en"].get(text, text)


def _translate_kwargs(kwargs: dict) -> dict:
    if "text" in kwargs:
        kwargs["text"] = tr(kwargs["text"])
    return kwargs


class LocalizedLabel(tk.Label):
    """tk.Label that translates its text."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **_translate_kwargs(kwargs))

    def configure(self, cnf=None, **kwargs):
        return super().configure(cnf, **_translate_kwargs(kwargs))

    config = configure


class LocalizedButton(tk.Button):
    """tk.Button that translates its text."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **_translate_kwargs(kwargs))

    def configure(self, cnf=None, **kwargs):
        return super().configure(cnf, **_translate_kwargs(kwargs))

    config = configure


class LocalizedRadiobutton(tk.Radiobutton):
    """tk.Radiobutton that translates its text."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **_translate_kwargs(kwargs))

    def configure(self, cnf=None, **kwargs):
        return super().configure(cnf, **_translate_kwargs(kwargs))

    config = configure


class LocalizedCheckbutton(tk.Checkbutton):
    """tk.Checkbutton that translates its text."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **_translate_kwargs(kwargs))

    def configure(self, cnf=None, **kwargs):
        return super().configure(cnf, **_translate_kwargs(kwargs))

    config = configure


class LocalizedTtkButton(ttk.Button):
    """ttk.Button that translates its text."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **_translate_kwargs(kwargs))

    def configure(self, cnf=None, **kwargs):
        return super().configure(cnf, **_translate_kwargs(kwargs))

    config = configure


class LocalizedLabelFrame(tk.LabelFrame):
    """tk.LabelFrame that translates its text."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **_translate_kwargs(kwargs))

    def configure(self, cnf=None, **kwargs):
        return super().configure(cnf, **_translate_kwargs(kwargs))

    config = configure


def _translate_messagebox_args(args, kwargs):
    if args and isinstance(args[0], str):
        args = (tr(args[0]),) + tuple(args[1:])
    if len(args) > 1 and isinstance(args[1], str):
        args = args[:1] + (tr(args[1]),) + tuple(args[2:])
    if "title" in kwargs:
        kwargs["title"] = tr(kwargs["title"])
    if "message" in kwargs:
        kwargs["message"] = tr(kwargs["message"])
    return args, kwargs


def showinfo(*args, **kwargs):
    args, kwargs = _translate_messagebox_args(args, kwargs)
    return messagebox.showinfo(*args, **kwargs)


def showwarning(*args, **kwargs):
    args, kwargs = _translate_messagebox_args(args, kwargs)
    return messagebox.showwarning(*args, **kwargs)


def showerror(*args, **kwargs):
    args, kwargs = _translate_messagebox_args(args, kwargs)
    return messagebox.showerror(*args, **kwargs)


def askyesno(*args, **kwargs):
    args, kwargs = _translate_messagebox_args(args, kwargs)
    return messagebox.askyesno(*args, **kwargs)


def askyesnocancel(*args, **kwargs):
    args, kwargs = _translate_messagebox_args(args, kwargs)
    return messagebox.askyesnocancel(*args, **kwargs)
