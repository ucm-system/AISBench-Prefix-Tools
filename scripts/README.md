# 手动脚本工具

本目录包含两个独立的命令行脚本，用于在没有 GUI 的情况下手动设计测试用例和解析测试结果。

---

## aisbench_test_designer.py — 交互式测试用例设计器

### 用途

终端交互式工具，引导你根据 KV cache 信息自动计算测试参数（请求数、并发数），生成可执行的 `.sh` 测试脚本。

### 运行方式

```bash
python3 aisbench_test_designer.py
```

### 操作流程

1. **输入 KV cache 信息**（从 vLLM 启动日志获取）
   - 单个 DP 组 KV cache size（tokens）
   - DP 组数（data-parallel-size）
   - 单条请求最大长度（tokens）

2. **选择输入长度** — 从预设值中选或自定义（需小于最大请求长度）

3. **选择输出长度** — 预设值如 512、1024

4. **设置前缀命中率** — 默认 0.9（90%）

5. **生成测试用例** — 自动计算：
   - 请求数 = `2 × total_kv_cache / input_len / repeat_rate`
   - 并发数 = `total_kv_cache / (input_len + output_len) × 0.9`

6. **调整参数** — 可批量乘系数调整请求数/并发数，或单独修改某个用例

7. **确认生成** — 输出 `run_aisbench_tests_<时间戳>.sh` 脚本

### 示例输出

生成的 `.sh` 脚本示例：

```bash
#!/bin/bash
LOG_DIR="./test_logs_20260909_200012"
mkdir -p ${LOG_DIR}

python3 aisbench_test.py \
  --prefix_test \
  --input_len 16384 \
  --output_len 512 \
  --data_num 120 \
  --prefix_num 120 \
  --concurrency 10 \
  --dataset_type prefix_cache \
  --repeat_rate 90% \
  --dp 4 \
  2>&1 | tee -a ${LOG_DIR}/test_16384_512.log
```

---

## extract_metrics.py — 测试日志性能指标提取

### 用途

从 AISBench 测试日志中提取**第二次测试（全量数据集测试）**的性能指标，输出 CSV 文件。

### 运行方式

```bash
python3 extract_metrics.py -d <日志目录> -o <输出CSV文件>
```

### 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `-d` / `--dir` | 日志目录路径（包含 `test_*.log` 文件） | `./test_logs_20260909_200012` |
| `-o` / `--output` | 输出 CSV 文件名（默认 `second_test_results.csv`） | `results.csv` |

### 示例

```bash
# 提取日志目录中所有测试结果
python3 extract_metrics.py -d ./test_logs_20260909_200012 -o results.csv
```

### 提取的指标

CSV 包含以下字段：

| 类别 | 字段 |
|------|------|
| 基本参数 | input_len, output_len, total_req, max_cc, cc |
| 命中率 | hbm_hit_rate, external_hit_rate |
| 延迟 | TTFT_avg/min/max, TPOT_avg/min/max, E2EL_avg/min/max |
| 吞吐量 | output_throughput, E2E_throughput, qps, input_token_throughput, prefill_token_throughput |

### 提取逻辑

1. 在日志中定位「全量数据集测试」标记
2. 从该位置之后提取 Performance Results 表格（TTFT/TPOT/E2EL）
3. 提取 Common Metrics（吞吐量、QPS、并发数）
4. 提取 Prefix cache hit summary（HBM/external 命中率）
5. 合并写入 CSV

---

## generate_docs_screenshots.py — 使用文档截图生成器

### 用途

自动启动当前 GUI，填充示例状态并截取 5 个向导步骤，输出到 `docs/images/`，用于刷新在线使用文档中的程序运行截图。

### 运行方式

```bash
python scripts/generate_docs_screenshots.py
```

### 输出

| 文件 | 对应步骤 |
|------|----------|
| `step1-connection-20261028.png` | SSH 连接 |
| `step2-docker-20261028.png` | Docker 部署与模型配置 |
| `step3-config-20261028.png` | 配置 `config.py` |
| `step4-testcases-20261028.png` | 设计测试用例 |
| `step5-execute-20261028.png` | 执行测试并生成 CSV |

脚本只填充示例数据，不会连接远程主机或启动容器。

---

## 典型使用流程

```bash
# 1. 用设计器生成测试脚本
python3 scripts/aisbench_test_designer.py
# → 生成 run_aisbench_tests_20260909_200012.sh

# 2. 在测试机上执行脚本
bash run_aisbench_tests_20260909_200012.sh
# → 生成 test_logs_20260909_200012/test_*.log

# 3. 提取结果到CSV
python3 scripts/extract_metrics.py -d test_logs_20260909_200012 -o results.csv
# → 生成 results.csv
```
