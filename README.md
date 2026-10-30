# AISBench-Prefix-Tools

[📚 在线使用文档](https://ucm-system.github.io/AISBench-Prefix-Tools/)
[🧭 在线设计文档](https://ucm-system.github.io/AISBench-Prefix-Tools/design.html)

Windows 桌面工具，用于远程部署 AISBench 测试环境并自动设计/执行 prefix cache 性能测试，自动提取结果生成 CSV。

## 界面语言

- 支持中文 / English 两种界面语言
- 在左侧边栏底部选择 `语言 / Language`，切换后界面立即重建，无需重启程序
- 界面控件、弹窗提示（如“下一步”校验、部署/清理确认）与状态栏动态消息均随语言切换
- 切换语言只改变界面呈现，不重置向导步骤、连接信息与已填写的配置
- 选择会保存到本机用户配置，下次启动自动恢复

## 项目模块

| 文件 | 职责 |
|------|------|
| `main.py` | GUI 主程序（5步向导） |
| `ssh_manager.py` | SSH/SFTP 远程连接、命令执行、文件传输 |
| `docker_manager.py` | 执行机镜像列表查询、已有镜像复用、tar 镜像加载、容器管理、代码导入容器、容器内脚本写入、日志下载、残留容器清理 |
| `config_manager.py` | config.py 配置文件生成并直接写入容器内部 |
| `test_designer.py` | 测试用例设计（KV cache 计算、.sh 脚本生成） |
| `log_parser.py` | 测试日志解析、CSV 结果生成 |
| `log_tools.py` | 远程日志工具：选择宿主机/容器日志，筛选 KV cache 并一键填入，查看日志内容 |
| `result_compare.py` | 结果对比分析：两个测试结果目录按输入规模匹配，差异表格 + 柱状对比图 + 导出 CSV |
| `i18n.py` | 中文 / English 界面文案与语言切换 |
| `settings_manager.py` | 用户偏好持久化（界面语言等） |
| `scripts/aisbench_test_designer.py` | 交互式命令行版测试用例设计器（与 GUI 逻辑一致） |

## 快速开始

### 方式一：直接下载 EXE（最简单）

- **最新稳定版**：从 [Releases](https://github.com/ucm-system/AISBench-Prefix-Tools/releases/latest) 页面下载（[直达链接](https://github.com/ucm-system/AISBench-Prefix-Tools/releases/latest/download/AISBench-Prefix-Tools.exe)）
- **Nightly 构建**（main 最新代码，CI 每次推送自动覆盖更新）：[直达链接](https://github.com/ucm-system/AISBench-Prefix-Tools/releases/download/nightly/AISBench-Prefix-Tools.exe)

双击即可运行，**无需安装 Python 和任何依赖**。

### 方式二：从源码运行

```bash
cd AISBench-Prefix-Tools
pip install -r requirements.txt
python main.py
```

### 方式三：自行打包 EXE（本地使用）

```bash
cd AISBench-Prefix-Tools
pip install -r requirements.txt
build_exe.bat
# 生成 dist/AISBench-Prefix-Tools.exe
```

---

## 使用流程（5 步向导）

### 步骤 1：SSH 连接执行机

| 字段 | 说明 | 示例 |
|------|------|------|
| 执行机 IP | 远程 Linux 服务器地址 | `141.xx.xx.xx` |
| SSH 端口 | 默认 22 | `22` |
| 用户名 | 通常 root | `root` |
| 密码 / 密钥 | 二选一 | 密码（右侧小眼睛可切换明文）或 `.pem` 密钥文件 |

点击 **测试连接** 确认后进入下一步。

---

### 步骤 2：Docker 部署与模型配置

| 字段 | 说明 |
|------|------|
| AISBench 镜像来源 | 点击 **查看已有镜像**，直接选择执行机上已存在的 Docker 镜像；未发现可用镜像时自动切换为 **上传本地镜像tar包**，并保留镜像下载链接 |
| 测试代码来源 | **程序内置**（默认，随 EXE 打包，部署时自动上传）或 **本地 zip 包**（zip 模式附代码下载链接按钮） |
| 模型路径 | 点击 **浏览远程目录** 在远程主机目录树中定位模型权重目录（下拉框保留历史路径） |
| 模型名称 | 对应 vLLM 的 `--served-model-name` 参数 |
| vLLM 服务 IP / 端口 | 模型推理服务地址 |
| API Key | 鉴权令牌，未开启鉴权则留空 |
| 临时部署目录 | 默认 `/tmp/AISBench_Prefix_Tools`；仅部署期间暂存镜像tar/代码，代码导入容器后自动删除，不保留在宿主机 |
| 残留容器清理 | 点击“清理残留容器”可查看并删除上次退出时未清理的 `aisbench-test-*` 容器 |

---

点击 **开始部署**，工具自动执行：

```
[1/5] 检查远程机 Docker 环境
[2/5] 准备 AISBench 镜像
        ↓ 已有镜像模式: 校验执行机镜像存在后直接复用
        ↓ 上传模式: 预读 manifest.json, 已存在则跳过, 否则 SFTP 上传并 docker load -i
[3/5] 暂存测试代码（程序内置 或 本地 zip 包）
[4/5] 创建并启动容器(仅挂载模型路径):
        docker run -itd \
          --name aisbench-test-MMDDHHMM  \  ← 自动生成容器名
          --shm-size=1g --net=host \
          --label org.aisbench-prefix-tools.managed=true \
          -v <模型路径>:<模型路径> \
          <镜像名> python3
[5/5] docker cp 导入测试代码到容器内 /benchmark/ais_bench/aisbench_auto_tools_prefix-main
        → 删除宿主机临时目录（部署成功后不再保留）
```

全程日志实时输出，部署完成后容器自动运行；后续 config.py、测试脚本与日志全部位于容器内部。

---

### 步骤 3：配置 config.py

工具自动生成配置文件并直接写入容器内部工作区（不依赖宿主机目录挂载），需确认以下字段：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| MODEL_NAME | `ds` | 来自步骤 2 |
| MODEL_PATH | - | 来自步骤 2 |
| HOST_IP | - | 来自步骤 2 |
| HOST_PORT | `8000` | 来自步骤 2 |
| API_KEY | 空 | 鉴权令牌 |
| DATASET_PATH | 自动填充 | 测试代码在容器内的工作区路径 |
| WORK_PATH | `/benchmark` | aisbench 工作路径 |
| DEFAULT_PERFORMANCE_TEST | `default_perf` | 稳态测试填 `stable_stage` |
| OUTPUT_DIR | `./outputs/default` | 日志输出路径 |
| POD_INFO | `[]` | **多 DP 场景必填**，格式 `ip:port,ip:port` |

点击 **保存配置到容器** 写入，右侧预览区可查看完整文件内容；点击 **验证配置(读取容器)** 可回读容器内 config.py 与界面值比对，存在差异时提示重新保存。

---

### 步骤 4：设计测试用例

填写 KV cache 信息（从 vLLM 启动日志获取）。界面内置查询命令，点击 **复制** 后可直接在服务器上执行：

```bash
cat vllm_serve.log | grep -e 'GPU KV cache size' -e 'Maximum concurrency'
```

也可以点击 **从日志自动获取 / 查看日志** 打开远程日志工具：

- **服务器**：当前执行机，或临时连接其他服务器（关闭对话框自动断开）
- **日志来源**：宿主机文件 / 指定容器内文件（自动列出运行中容器）/ 容器 stdout（docker logs）
- **筛选 KV cache**：对选定日志执行 grep，直接显示匹配行；解析出"单个DP组KV cache"与"模型最大上下文"后可**一键填入**，同时界面查询命令更新为实际执行命令
- **查看日志**：独立窗口查看日志内容（文件取尾部 2MB，docker logs 取尾部 5000 行，支持横向滚动与一键复制）

| 字段 | 说明 | 示例 |
|------|------|------|
| 单个DP组KV cache | 单 DP 组的 cache 容量 | `198469` |
| DP组数 | data-parallel-size | `4` |
| 最大请求长度 | 单条请求最大 token 数 | `32768` |
| 前缀命中率 | repeat_rate，0~1 | `0.9` |
| 请求发送速率 | 0 = Burst 模式；>0 为固定发送速率 (req/s)，支持小数如 `0.3` | `0` |

勾选测试的 **输入长度**（预设 8K ~ 2M，超出模型最大上下文的选项生成时会明确提示跳过）和 **输出长度**，点击 **生成测试用例**。

工具自动计算（下方"计算明细"面板展示每个用例的代入过程）：
- **最小请求数** = `floor(total_kv_cache / input_len / repeat_rate) + 1`
  （低于该值时请求前缀总量不会超出 HBM KV cache 容量，不会命中 HBM 之外的 KV cache 缓存介质）
- **推荐请求数** = 最小请求数 × 2
- **并发数** = `floor(total_kv_cache / (input_len + output_len))`（KV cache 使用率 ≈ 100%）

生成的用例表格包含 **请求数(推荐) / 请求数(最小) / 并发数 / KV使用率** 列（表格与计算明细区域可拖拽分隔条调整占比），支持：
- **双击单元格** 编辑 Input / Output / 请求数 / 并发数
- 请求数允许低于最小值，低于时仅弹窗提醒（提示不会命中 HBM 之外的缓存介质），不强制拦截
- **添加用例 / 复制用例 / 删除用例** 按钮管理用例列表

---

### 步骤 5：执行测试（自动生成CSV）

点击 **执行测试 → 生成CSV**，工具自动完成以下阶段：

```
[0/4] 预检查: 验证容器内 MODEL_PATH
        ↓ 路径存在且含 config.json，否则快速失败并提示原因
[1/4] 生成 .sh 测试脚本
        ↓ test_designer 生成包含所有测试用例的 bash 脚本
[2/4] 写入测试脚本到容器内部并执行
        ↓ base64 编码写入 run_tests.sh → 容器内 bash run_tests.sh
[3/4] 下载测试日志到本地
        ↓ docker cp 容器日志 → SFTP 下载到 Windows 本地目录
[4/4] 解析日志生成 CSV
        ↓ log_parser 解析第二次测试结果，输出 CSV 到本地
```

生成的测试命令示例：

```bash
python3 aisbench_test.py \
  --prefix_test \
  --input_len 16384 \
  --output_len 512 \
  --data_num 108 \
  --prefix_num 108 \
  --concurrency 46 \
  --dataset_type prefix_cache \
  --repeat_rate 90% \
  --dp 4 \
  --seed 385712
```

其中 `--seed` 每次执行随机生成（数据集可复现、不同轮次不同）；请求发送速率 > 0 时还会追加 `--request_rate <速率>`。

**本地结果保存目录**：步骤 5 界面上可选择 Windows 本地目录（默认 `C:\Users\<用户名>\aisbench_results`）。

测试完成后自动产出：
- **CSV 文件**：`results_test_logs_<时间戳>.csv`（包含 TTFT/TPOT/E2EL、吞吐量、命中率等指标）
- **日志文件**：`test_logs_<时间戳>/test_<序号>_<input>_<output>.log`（每个用例独立文件，同长度多测试也能分别解析出结果）

执行日志区域实时输出进度（自动跟随最新输出，向上翻阅查看历史时不强制滚动），命令预览 / 执行日志 / 结果摘要区域可拖拽分隔条调整占比。完成后在界面底部 **结果摘要表格** 中直接展示关键指标（Input / Output / 请求数 / 最大并发 / 并发 / 输入吞吐 / 输出吞吐 / TTFT / TPOT / QPS / HBM 命中率 / 外部缓存命中率，并标注 CSV 与日志路径），同时日志区也打印文本摘要表：

```
结果摘要:
-----------------------------------------------------------------------------------------------------------------------------
   Input   Output    Req   Max_CC       CC    In_Tput   Out_Tput   TTFT_avg   TPOT_avg      QPS   HBM_Hit%   Ext_Hit%
   16384      512    108       46       46     4523.1      312.5       45.2       12.3      8.5       92.3       91.8
   16384     1024    108       45       45     4410.8      290.1       48.1       11.8      7.2       92.5       91.6
   32768      512     54       23       23     3895.4      201.7       52.6       13.1      6.1       94.8       95.1
-----------------------------------------------------------------------------------------------------------------------------
```

### 结果对比分析

结果对比分析为**独立工具，无需连接执行服务器**，两种入口随时可用：

- 左侧边栏 **📊 结果对比分析** 按钮（应用启动后即可使用）
- 步骤 5 **结果摘要** 栏右侧按钮（测试完成后就近使用）

选择两个工具生成的结果 CSV 文件（`results_*.csv`）：

- **格式校验**：表头字段必须与工具生成的 CSV 格式完全一致，缺少/多余字段会明确提示
- **用例匹配**：先按（输入长度 + 输出长度）精确匹配，剩余用例回退按输入长度匹配（标注匹配方式）；匹配列表同时展示两侧请求数与 Max_CC；勾选参与对比的用例
- **指标选择**：21 个指标按 TTFT / TPOT / E2E 延迟 / 吞吐 / 命中率分组勾选，默认选中常用 6 项
- **差异表格**：Req A/B、Max_CC A/B 两列 + 每个指标 4 列（A 值 / B 值 / Δ = B−A / Δ%），支持横向滚动
- **柱状对比图**：每个指标自动绘制分组柱状图（A 蓝 / B 橙，CSV 文件名为图例），横坐标展示 输入/输出/请求数/Max_CC（两侧不同以 A↔B 标注），随窗口宽度自适应
- **导出对比 CSV**：将当前对比表格保存为 CSV 文件

### 环境清理与退出

- 测试完成后会自动提醒是否清理远程环境（停止并删除容器 + 删除残留暂存文件），本地结果不受影响
- 也可随时点击 **清理环境** 按钮手动清理
- 退出程序时（点击 **完成** 或窗口 **×**），若检测到容器仍在运行，会再次弹出清理提醒：清理后退出 / 保留环境直接退出 / 取消
- 若上次退出时未清理容器，本次连接成功后会自动扫描 `aisbench-test-*` 容器并提醒；也可在步骤 2 点击 **清理残留容器** 勾选删除（支持同时清理旧版遗留的临时目录）
- 残留容器清理只识别本工具创建的容器（`aisbench-test-` 前缀或管理 label），不会影响执行机上的其他容器

---

## 测试结果提取（独立使用）

如果不使用 GUI，也可单独运行日志解析脚本提取性能指标：

```bash
python log_parser.py
# 或在代码中调用
# from log_parser import parse_log_directory
# parse_log_directory("/path/to/test_logs", "results.csv")
```

CSV 包含字段：input_len, output_len, total_req, max_cc, cc, hbm_hit_rate, external_hit_rate, TTFT_avg/min/max/P90, TPOT_avg/min/max/SLO_P90, E2E_time, E2EL_avg/min/max/P90, output_throughput, E2E_throughput, input_token_throughput, prefill_token_throughput, qps, qpm。

---

## 常见问题

**Q: 执行机上已有镜像，还需要上传 tar 包吗？**
A: 不需要。在步骤 2 点击 **查看已有镜像**，从列表选择镜像后直接部署；工具会校验该镜像仍存在并跳过上传与加载。未发现可用镜像时才需要切换到上传模式。

**Q: 上传镜像后无法自动识别镜像名？**
A: 工具优先在本地直接读取 tar 包内 `manifest.json` 获取镜像名（无需上传）；读取失败时再由 `docker load` 输出的 `Loaded image:` 行识别。可在步骤 2 部署日志中查看解析结果。

**Q: 如何切换中文 / English 界面？**
A: 在左侧边栏底部选择 `语言 / Language`；界面会立即重建，选择会保存到本机用户配置，下次启动自动恢复。

**Q: 模型路径浏览看不到文件？**
A: 远程目录浏览器默认从 `/` 开始，双击 `[DIR]` 进入子目录。部分目录可能因权限问题无法列出。

**Q: POD_INFO 怎么填？**
A: 单 DP 场景留空即可（自动使用 HOST_IP:HOST_PORT）。多 DP 场景填写每个节点的地址，逗号分隔，如 `141.1.1.11:8000,141.1.1.12:8000`。

**Q: 如何重新部署？**
A: 再次点击 **开始部署** 会自动删除同名旧容器并重新创建。也可手动 `docker rm -f <容器名>` 后重试。

**Q: 上次退出没有清理，怎么删除遗留容器？**
A: 重新连接执行机后，工具会自动扫描 `aisbench-test-*` 容器并提醒；也可以在步骤 2 点击 **清理残留容器**，在列表中勾选要删除的容器（可同时清理旧版本遗留的 `/tmp/AISBench_Prefix_Tools` 临时目录）。清理只针对本工具创建的容器。

**Q: 远程的 /tmp/AISBench_Prefix_Tools 目录为什么部署后不见了？**
A: 该目录现在只是部署过程的临时暂存区，用于上传镜像 tar/测试代码。代码通过 `docker cp` 导入容器后，工具会自动删除该目录；后续 config.py、测试脚本和日志都保存在容器内部，不再依赖宿主机目录。

**Q: SSH 连接超时？**
A: 检查防火墙、安全组是否放行 SSH 端口；确认 IP 和端口正确；如使用密钥，确保密钥格式为 RSA 或 Ed25519。
