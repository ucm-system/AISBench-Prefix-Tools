# AISBench Deployer

Windows 桌面工具，用于远程部署 AISBench 测试环境并自动设计/执行 prefix cache 性能测试，自动提取结果生成 CSV。

## 项目模块

| 文件 | 职责 |
|------|------|
| `main.py` | GUI 主程序（6步向导） |
| `ssh_manager.py` | SSH/SFTP 远程连接、命令执行、文件传输 |
| `docker_manager.py` | Docker 镜像加载、容器管理、脚本上传运行、日志下载 |
| `config_manager.py` | config.py 配置文件生成与写入 |
| `test_designer.py` | 测试用例设计（KV cache 计算、.sh 脚本生成） |
| `log_parser.py` | 测试日志解析、CSV 结果生成 |

## 快速开始

### 方式一：直接下载 EXE（最简单）

- **最新稳定版**：从 [Releases](https://github.com/student-jhz/AISBench-Prefix-Tools/releases/latest) 页面下载（[直达链接](https://github.com/student-jhz/AISBench-Prefix-Tools/releases/latest/download/AISBench-Prefix-Tools.exe)）
- **Nightly 构建**（main 最新代码，CI 每次推送自动覆盖更新）：[直达链接](https://github.com/student-jhz/AISBench-Prefix-Tools/releases/download/nightly/AISBench-Prefix-Tools.exe)

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

## 使用流程（6 步向导）

### 步骤 1：SSH 连接执行机

| 字段 | 说明 | 示例 |
|------|------|------|
| 执行机 IP | 远程 Linux 服务器地址 | `141.xx.xx.xx` |
| SSH 端口 | 默认 22 | `22` |
| 用户名 | 通常 root | `root` |
| 密码 / 密钥 | 二选一 | 密码或 `.pem` 密钥文件 |

点击 **测试连接** 确认后进入下一步。

---

### 步骤 2：选择文件与模型

| 字段 | 说明 |
|------|------|
| 镜像 tar 包 | 本地选择 AISBench Docker 镜像 `.tar` 文件 |
| 代码 zip 包 | 本地选择 `aisbench_auto_tools_prefix` 的 `.zip`，或点击 **从GitHub下载** 自动拉取 |
| 模型路径 | 点击 **浏览远程目录** 在远程主机目录树中定位模型权重目录 |
| 模型名称 | 对应 vLLM 的 `--served-model-name` 参数 |
| vLLM 服务 IP / 端口 | 模型推理服务地址 |
| API Key | 鉴权令牌，未开启鉴权则留空 |

---

### 步骤 3：Docker 部署（自动完成）

点击 **开始部署**，工具自动执行：

```
1. 上传镜像 tar 包到远程主机
2. docker load -i <tar>            → 自动解析镜像名
3. 上传并解压代码 zip 包到远程主机
4. docker run -itd \
     --name aisbench-test-MMDDHHMM  \  ← 自动生成容器名
     --shm-size=1g \
     --net=host \
     -v <模型路径>:<模型路径> \
     -v <代码目录>:/benchmark/ais_bench/aisbench_auto_tools_prefix-main \
     <镜像名> python3
```

全程日志实时输出，部署完成后容器自动运行。

---

### 步骤 4：配置 config.py

工具自动生成配置文件并写入容器，需确认以下字段：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| MODEL_NAME | `ds` | 来自步骤 2 |
| MODEL_PATH | - | 来自步骤 2 |
| HOST_IP | - | 来自步骤 2 |
| HOST_PORT | `8000` | 来自步骤 2 |
| API_KEY | 空 | 鉴权令牌 |
| DATASET_PATH | 自动填充 | 代码包在容器内的挂载路径 |
| WORK_PATH | `/benchmark` | aisbench 工作路径 |
| DEFAULT_PERFORMANCE_TEST | `default_perf` | 稳态测试填 `stable_stage` |
| OUTPUT_DIR | `./outputs/default` | 日志输出路径 |
| POD_INFO | `[]` | **多 DP 场景必填**，格式 `ip:port,ip:port` |

点击 **保存配置到容器** 写入，右侧预览区可查看完整文件内容。

---

### 步骤 5：设计测试用例

填写 KV cache 信息（从 vLLM 启动日志获取）：

| 字段 | 说明 | 示例 |
|------|------|------|
| 单个DP组KV cache | 单 DP 组的 cache 容量 | `198469` |
| DP组数 | data-parallel-size | `4` |
| 最大请求长度 | 单条请求最大 token 数 | `32768` |
| 前缀命中率 | repeat_rate，0~1 | `0.9` |
| 请求发送速率 | 0 = Burst 模式 | `0` |

勾选测试的 **输入长度** 和 **输出长度**，点击 **生成测试用例**。

工具自动计算：
- **请求数** = `2 × total_kv_cache / input_len / repeat_rate`（确保覆盖 KV cache 容量的 2 倍）
- **并发数** = `total_kv_cache / (input_len + output_len) × 0.9`（确保 KV cache 使用率 ≈ 90%）

可一键 **×0.5 / ×2** 批量调整请求数或并发数。

---

### 步骤 6：执行测试（自动生成CSV）

点击 **执行测试 → 生成CSV**，工具自动完成 4 个阶段：

```
[1/4] 生成 .sh 测试脚本
        ↓ test_designer 生成包含所有测试用例的 bash 脚本
[2/4] 上传脚本到容器并执行
        ↓ docker write_script → docker run_script (容器内 bash run_tests.sh)
[3/4] 下载测试日志到本地
        ↓ SFTP 下载 test_*.log 文件到 Windows 本地目录
[4/4] 解析日志生成 CSV
        ↓ log_parser 解析第二次测试结果，输出 CSV 到本地
```

生成的测试命令示例：

```bash
python3 aisbench_test.py \
  --prefix_test \
  --input_len 16384 \
  --output_len 512 \
  --data_num 120 \
  --prefix_num 120 \
  --concurrency 10 \
  --dataset_type prefix_cache \
  --repeat_rate 90% \
  --dp 4
```

**本地结果保存目录**：步骤 6 界面上可选择 Windows 本地目录（默认 `C:\Users\<用户名>\aisbench_results`）。

测试完成后自动产出：
- **CSV 文件**：`results_test_logs_<时间戳>.csv`（包含 TTFT/TPOT/E2EL、吞吐量、命中率等指标）
- **日志文件**：`test_logs_<时间戳>/test_<input>_<output>.log`（原始测试日志）

执行日志区域实时输出进度，完成后在界面底部 **结果摘要表格** 中直接展示关键指标（Input/Output/请求数/并发/吞吐/TTFT/TPOT/QPS/命中率，并标注 CSV 与日志路径），同时日志区也打印文本摘要表：

```
结果摘要:
--------------------------------------------------------------------------------
  Input   Output   TTFT_avg    TPOT_avg      QPS   Ext_Hit%
   16384     512       45.2        12.3     8.5       92.3
   16384    1024       48.1        11.8     7.2       91.8
   32768     512       52.6        13.1     6.1       95.1
--------------------------------------------------------------------------------
```

---

## 测试结果提取（独立使用）

如果不使用 GUI，也可单独运行日志解析脚本提取性能指标：

```bash
python log_parser.py
# 或在代码中调用
# from log_parser import parse_log_directory
# parse_log_directory("/path/to/test_logs", "results.csv")
```

CSV 包含字段：input_len, output_len, total_req, max_cc, cc, hbm_hit_rate, external_hit_rate, TTFT_avg/min/max, TPOT_avg/min/max, E2EL_avg/min/max, output_throughput, E2E_throughput, qps, prefill_token_throughput 等。

---

## 常见问题

**Q: 镜像加载后无法自动识别镜像名？**
A: 工具解析 `docker load` 输出的 `Loaded image:` 行。若镜像打包格式异常，可手动在步骤 3 日志中找到镜像名，重新部署。

**Q: 模型路径浏览看不到文件？**
A: 远程目录浏览器默认从 `/` 开始，双击 `[DIR]` 进入子目录。部分目录可能因权限问题无法列出。

**Q: POD_INFO 怎么填？**
A: 单 DP 场景留空即可（自动使用 HOST_IP:HOST_PORT）。多 DP 场景填写每个节点的地址，逗号分隔，如 `141.1.1.11:8000,141.1.1.12:8000`。

**Q: 如何重新部署？**
A: 再次点击 **开始部署** 会自动删除同名旧容器并重新创建。也可手动 `docker rm -f <容器名>` 后重试。

**Q: SSH 连接超时？**
A: 检查防火墙、安全组是否放行 SSH 端口；确认 IP 和端口正确；如使用密钥，确保密钥格式为 RSA 或 Ed25519。
