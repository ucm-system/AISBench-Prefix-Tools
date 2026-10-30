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
        '提示': 'Notice',
        '成功': 'Success',
        '失败': 'Failed',
        '警告': 'Warning',
        '错误': 'Error',
        '连接失败': 'Connection failed',
        '清理提醒': 'Cleanup reminder',
        '确认清理': 'Confirm cleanup',
        '发现残留容器': 'Residual containers found',
        '配置验证失败': 'Config validation failed',
        '配置不一致': 'Config mismatch',
        '验证通过': 'Verification passed',
        '打开失败': 'Open failed',
        '临时目录已存在': 'Temporary directory already exists',
        '输入长度超出限制': 'Input length exceeds the limit',
        '请求数低于最小值': 'Request count below minimum',
        '参数超出限制': 'Parameter exceeds the limit',
        '清理完成': 'Cleanup complete',
        '请填写IP和用户名': 'Please enter IP and username',
        '请填写密码或密钥文件路径': 'Please enter the password or key file path',
        '请先连接到远程主机': 'Please connect to the remote host first',
        '请输入临时部署目录路径': 'Please enter the temporary deploy directory path',
        '请先完成模型路径选择': 'Please finish model path selection first',
        '请先完成Docker部署': 'Please finish Docker deployment first',
        '写入config.py失败': 'Failed to write config.py',
        'config.py 已写入，但回读失败，请点击"验证配置"手动检查': 'config.py was written, but read-back failed; click "Verify config" to check manually',
        '无法从容器读取config.py\n可能原因: 1)未点击"保存配置到容器" 2)路径错误 3)SSH连接断开': 'Cannot read config.py from the container\nPossible causes: 1) "Save config to container" not clicked 2) wrong path 3) SSH connection lost',
        '请先选择要复制的用例行': 'Please select a case row to copy first',
        '请先选择要删除的用例行': 'Please select a case row to delete first',
        '至少保留一个测试用例': 'Keep at least one test case',
        '请求发送速率输入无效, 请输入数字\n(支持小数如 0.3; 0 表示Burst模式)': 'Invalid request send rate; enter a number\n(decimals supported, e.g. 0.3; 0 means Burst mode)',
        '测试已完成，是否退出程序?': 'Tests completed. Exit the program?',
        '请先点击列表行勾选要清理的容器': 'Please click list rows to select containers to clean',
        '请选择本地代码zip包 (或改用程序内置)': 'Please select a local code zip package (or use built-in)',
        '请先查看并选择执行机上的镜像': 'Please view and select an image on the execution host first',
        '请选择要上传的AISBench镜像tar包': 'Please select the AISBench image tar package to upload',
        'Docker部署完成!': 'Docker deployment complete!',
        '请输入有效的数字\n(请求发送速率支持小数, 如 0.3 表示 0.3 req/s; 0 表示Burst模式)': 'Please enter a valid number\n(the request send rate supports decimals, e.g. 0.3 = 0.3 req/s; 0 means Burst mode)',
        '没有有效的输入长度': 'No valid input lengths',
        '请输入有效的输入/输出长度': 'Please enter valid input/output lengths',
        '请求数和并发数必须为数字': 'Request count and concurrency must be numbers',
        '测试已完成但未提取到有效结果，请检查执行日志': 'Tests completed but no valid results were extracted; check the execution log',
        '环境清理完成!\n容器已删除, 临时目录无残留。\n本地测试结果不受影响。': 'Environment cleanup complete!\nContainer removed, no temporary directory leftovers.\nLocal test results are not affected.',
        '请完成镜像和模型路径选择': 'Please finish image and model path selection',
        '尚未生成测试用例，是否继续?': 'No test cases generated yet. Continue?',
        'Docker容器尚未部署，是否继续?': 'Docker container is not deployed yet. Continue?',
        '✗ 未提取到有效结果，请检查执行日志': '✗ No valid results extracted; check the execution log',
        '临时目录已清理': 'Temporary directory cleaned',
        '确定停止并删除以下容器?\n\n': 'Stop and delete the following containers?\n\n',
        '请点击"保存配置到容器"重新写入': 'Click "Save config to container" to rewrite',
        '\n\n请点击"保存配置到容器"重新写入':
            '\n\nClick "Save config to container" to rewrite',
        '容器未运行，请先完成部署': 'Container is not running; finish deployment first',
        '请先生成测试用例': 'Please generate test cases first',
        '请选择本地结果保存目录': 'Please select a local result directory',
        '容器名': 'Container',
        '镜像': 'Image',
        '状态': 'Status',
        '创建时间': 'Created',
        '容器内实际 config.py 内容:': 'Actual config.py content in container:',
        '界面与容器内config.py存在差异:\n\n': 'UI and container config.py differ:\n\n',
        'MODEL_NAME 不能为空': 'MODEL_NAME cannot be empty',
        'MODEL_PATH 不能为空': 'MODEL_PATH cannot be empty',
        'HOST_IP 不能为空': 'HOST_IP cannot be empty',
        'HOST_PORT 不能为空': 'HOST_PORT cannot be empty',
        '未连接到远程主机': 'Not connected to the remote host',
        '认证失败，请检查用户名/密码/密钥': 'Authentication failed; check username/password/key',
        'config.py 已写入，但回读发现以下不一致:\n\n': 'config.py was written, but read-back found these mismatches:\n\n',
        '已清理: {work_dir}': 'Cleaned: {work_dir}',
        '清理失败: {work_dir}': 'Cleanup failed: {work_dir}',
        '确定要清理临时部署目录吗?\n\n{work_dir}\n\n这将删除残留的暂存文件（镜像tar、代码包等），\n并停止当前会话创建的容器。\n容器内的测试代码和日志不受影响。': 'Clean the temporary deploy directory?\n\n{work_dir}\n\nThis deletes leftover staging files (image tar, code package, etc.)\nand stops containers created in this session.\nTest code and logs inside the container are not affected.',
        '发现 {count} 个本工具容器{suffix}': 'Found {count} tool container(s){suffix}',
        '检测到 {count} 个本工具创建的历史容器:\n\n{listing}\n\n这些容器可能是上次退出时未清理的。\n是否打开清理窗口进行选择清理?': 'Detected {count} historical container(s) created by this tool:\n\n{listing}\n\nThey may be leftovers from a previous run.\nOpen the cleanup window to clean them selectively?',
        '\n\n同时删除临时部署目录:\n  {work_dir}': '\n\nAlso delete the temporary deploy directory:\n  {work_dir}',
        '查询失败: {error}': 'Query failed: {error}',
        '共 {count} 个容器': '{count} container(s) in total',
        '发现 {count} 个本工具容器': 'Found {count} tool container(s)',
        '停止并删除容器: {name}\n': 'Stopping and removing container: {name}\n',
        'config.py 已写入并回读验证一致!\n\n容器内路径: {path}\n\n关键配置:\n  MODEL_PATH = {model_path}\n  MODEL_NAME = {model_name}\n  HOST_IP    = {host_ip}\n  HOST_PORT  = {host_port}': 'config.py written and verified by read-back!\n\nPath in container: {path}\n\nKey settings:\n  MODEL_PATH = {model_path}\n  MODEL_NAME = {model_name}\n  HOST_IP    = {host_ip}\n  HOST_PORT  = {host_port}',
        '容器内config.py与界面配置一致!\n\n{report}\n\nMODEL_PATH = {model_path}': 'config.py in the container matches the UI!\n\n{report}\n\nMODEL_PATH = {model_path}',
        '共 {count} 条记录  |  CSV: {csv_path}  |  日志: {log_dir}': '{count} records  |  CSV: {csv_path}  |  Log: {log_dir}',
        '无法打开链接: {url}\n{error}': 'Cannot open link: {url}\n{error}',
        '临时部署目录已存在且有内容:\n{work_dir}\n\n目录内容:\n{content}\n\n通常是上次部署失败或旧版本遗留的暂存文件。\n\n是 - 删除残留暂存文件\n否 - 忽略并继续部署(会覆盖同名文件)\n取消 - 保持现状': 'The temporary deploy directory already exists and is not empty:\n{work_dir}\n\nContents:\n{content}\n\nThese are usually staging files left by a failed deployment or an older version.\n\nYes - delete leftover staging files\nNo - ignore and continue (same-name files will be overwritten)\nCancel - keep current state',
        '未找到内置测试代码目录:\n{code_dir}\n\n请改用本地zip包模式': 'Built-in test code directory not found:\n{code_dir}\n\nPlease switch to the local zip package mode',
        'zip包不存在: {path}': 'Zip package does not exist: {path}',
        '镜像tar包不存在: {path}': 'Image tar package does not exist: {path}',
        '临时部署目录已存在且有内容:\n{work_dir}\n\n通常是上次部署中断或旧版本遗留的暂存文件。\n\n是 - 删除残留后继续部署\n否 - 忽略并继续部署（覆盖同名文件）\n取消 - 终止部署': 'The temporary deploy directory already exists and is not empty:\n{work_dir}\n\nThese are usually staging files left by an interrupted deployment or an older version.\n\nYes - delete leftovers and continue\nNo - ignore and continue (same-name files will be overwritten)\nCancel - abort deployment',
        '  {field}: 界面={gui}  容器={container}': '  {field}: UI={gui}  container={container}',
        '  {field}: 容器中未找到': '  {field}: not found in container',
        '以下选中的输入长度超过模型最大上下文 ({max_len:,})，已跳过:\n  {skipped}\n\n实际生成用例使用的输入长度: {kept}': 'Selected input lengths exceed the model max context ({max_len:,}) and were skipped:\n  {skipped}\n\nInput length actually used for generated cases: {kept}',
        '所选输入长度全部超过模型最大上下文 ({max_len:,}):\n  {skipped}\n\n已自动改用有效长度: {fallback}': 'All selected input lengths exceed the model max context ({max_len:,}):\n  {skipped}\n\nAutomatically switched to a valid length: {fallback}',
        '请求数 ({count:,}) 低于最小请求数 ({min_count:,})\n\n低于该值时, 请求前缀总量不会超出HBM KV Cache容量, 不会在HBM之外的KV Cache缓存介质中命中。\n\n如需覆盖HBM之外的缓存介质, 请将请求数提高至 {raise_to:,} 及以上。': 'Request count ({count:,}) is below the minimum ({min_count:,}).\n\nBelow this value, the total request prefix size will not exceed the HBM KV cache capacity, so nothing will hit in KV cache media outside HBM.\n\nTo cover cache media outside HBM, raise the request count to {raise_to:,} or higher.',
        '  ⚠ {field}: 界面=[{gui}]  容器=[{container}]': '  ⚠ {field}: UI=[{gui}]  container=[{container}]',
        '  ✓ {field}: {value}': '  ✓ {field}: {value}',
        '输入+输出长度 ({input_len:,}+{output_len:,}={total:,}) 超过模型最大上下文 ({max_len:,})': 'Input+output length ({input_len:,}+{output_len:,}={total:,}) exceeds the model max context ({max_len:,})',
        'HOST_PORT 必须为数字: {port}': 'HOST_PORT must be a number: {port}',
        "POD_INFO项格式应为 'ip:port': {item}": "POD_INFO items must have the format 'ip:port': {item}",
        '连接成功: {host}:{port}': 'Connected: {host}:{port}',
        'SSH连接错误: {error}': 'SSH connection error: {error}',
        '连接失败: {error}': 'Connection failed: {error}',
        '查询失败: {error}。可先上传tar包，部署时会检查Docker。': 'Query failed: {error}. You can upload a tar package first; Docker will be checked during deployment.',
        '发现 {count} 个镜像，请选择AISBench镜像；如无合适镜像，请切换为上传tar包。': 'Found {count} image(s). Select an AISBench image; if none is suitable, switch to uploading a tar package.',
        'ID {id} · 创建于 {created} · 大小 {size}': 'ID {id} · created {created} · size {size}',
        '已选择 {selected} ({detail})': 'Selected {selected} ({detail})',
        '测试完成!\n\nCSV: {csv}\n日志: {log}\n共 {count} 条记录': 'Tests complete!\n\nCSV: {csv}\nLog: {log}\n{count} records in total',
        '  - 临时部署目录残留: {work_dir} (正常情况下已自动清理)\n': '  - Temporary deploy directory leftovers: {work_dir} (normally cleaned automatically)\n',
        '测试已完成! 建议清理远程环境:\n\n  - Docker容器: {container}\n{work_dir_line}\n是否立即清理?\n(是: 停止并删除容器 + 删除残留暂存文件, 本地结果不受影响)\n(否: 稍后可点击"清理环境"按钮手动清理)': 'Tests complete! Cleaning up the remote environment is recommended:\n\n  - Docker container: {container}\n{work_dir_line}\nClean up now?\n(Yes: stop and remove the container + delete leftover staging files; local results are not affected)\n(No: you can click the "Clean environment" button later)',
        '  Docker容器: {container}\n': '  Docker container: {container}\n',
        '  临时部署目录: {work_dir} (如有残留)\n': '  Temporary deploy directory: {work_dir} (if any leftovers)\n',
        '确认清理以下远程资源?\n\n{container_line}{work_dir_line}\n清理后容器将停止删除, 残留暂存文件将被清除。\n本地下载的测试结果不受影响。\n': 'Clean the following remote resources?\n\n{container_line}{work_dir_line}The container will be stopped and removed, and leftover staging files will be deleted.\nDownloaded local test results are not affected.\n',
        '  临时部署目录残留: {work_dir} (如有)\n': '  Temporary deploy directory leftovers: {work_dir} (if any)\n',
        '检测到Docker容器仍在运行!\n\n  容器: {container}\n{work_dir_line}\n退出前是否清理远程环境?\n(是: 清理后退出  否: 直接退出保留容器  取消: 不退出)\n(未清理的容器下次连接时可通过步骤2"清理残留容器"删除)': 'The Docker container is still running!\n\n  Container: {container}\n{work_dir_line}Clean up the remote environment before exiting?\n(Yes: clean up and exit  No: exit and keep the container  Cancel: do not exit)\n(Uncleaned containers can be removed via "Clean residual containers" in step 2 on the next connection)',
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


def trf(text: str, *args, **kwargs) -> str:
    """Translate a message template, then apply str.format."""
    return tr(text).format(*args, **kwargs)


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
