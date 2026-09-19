"""
测试用例设计器 - 根据KV cache等信息生成测试用例
逻辑与交互式设计器一致，提供程序化接口供GUI调用
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class TestCase:
    """单个测试用例"""
    input_len: int
    output_len: int
    data_num_recommended: int
    data_num_min: int
    concurrency_recommended: int
    concurrency_max: int
    repeat_rate: float
    dp: int
    is_custom: bool = False

    def to_dict(self) -> dict:
        return {
            'input_len': self.input_len,
            'output_len': self.output_len,
            'data_num_recommended': self.data_num_recommended,
            'data_num_min': self.data_num_min,
            'concurrency_recommended': self.concurrency_recommended,
            'concurrency_max': self.concurrency_max,
            'repeat_rate': self.repeat_rate,
            'dp': self.dp,
            'is_custom': self.is_custom,
        }


class TestDesigner:
    """测试用例设计器"""

    PRESET_INPUT_LENGTHS = [8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576, 2097152]
    PRESET_OUTPUT_LENGTHS = [128, 256, 512, 1024, 2048]

    def __init__(self):
        self.single_kv_cache: int = 0
        self.dp: int = 1
        self.total_kv_cache: int = 0
        self.max_request_length: int = 0
        self.input_lengths: List[int] = []
        self.output_lengths: List[int] = []
        self.repeat_rate: float = 0.9
        self.request_rate: int = 0
        self.test_cases: List[TestCase] = []

    def set_kv_cache_info(self, single_kv_cache: int, dp: int, max_request_length: int):
        """设置KV cache信息"""
        self.single_kv_cache = single_kv_cache
        self.dp = dp
        self.total_kv_cache = single_kv_cache * dp
        self.max_request_length = max_request_length

    def get_valid_preset_inputs(self) -> List[int]:
        """获取小于最大请求长度的预设输入长度"""
        return [l for l in self.PRESET_INPUT_LENGTHS if l < self.max_request_length]

    def set_input_lengths(self, lengths: List[int]) -> List[int]:
        """设置输入长度; 返回因超出模型最大上下文被过滤的长度列表"""
        valid = [l for l in lengths if l < self.max_request_length]
        skipped = [l for l in lengths if l >= self.max_request_length]
        if not valid:
            valid = self.get_valid_preset_inputs()[:2] or [16384, 32768]
        self.input_lengths = sorted(set(valid))
        return skipped

    def set_output_lengths(self, lengths: List[int]):
        """设置输出长度"""
        if not lengths:
            lengths = [512, 1024]
        self.output_lengths = sorted(set(lengths))

    def set_repeat_rate(self, rate: float):
        """设置前缀命中率"""
        self.repeat_rate = max(0.0, min(1.0, rate))

    def set_request_rate(self, rate: float):
        """设置请求发送速率 (0=Burst, >0 为 req/s, 支持小数如 0.3)"""
        rate = max(0.0, float(rate))
        # 整数值归一化为 int, 避免命令/摘要中出现 "1.0"
        self.request_rate = int(rate) if rate.is_integer() else rate

    def generate_test_cases(self):
        """生成推荐的测试参数"""
        self.test_cases = []

        for input_len in self.input_lengths:
            for output_len in self.output_lengths:
                max_concurrency = int(self.total_kv_cache / (input_len + output_len))
                max_concurrency = max(1, max_concurrency)

                min_data_num = int(self.total_kv_cache / input_len / self.repeat_rate) + 1
                min_data_num = max(min_data_num, max_concurrency * 2)

                recommended_data_num = min_data_num * 2

                self.test_cases.append(TestCase(
                    input_len=input_len,
                    output_len=output_len,
                    data_num_recommended=recommended_data_num,
                    data_num_min=min_data_num,
                    concurrency_recommended=max_concurrency,
                    concurrency_max=max_concurrency,
                    repeat_rate=self.repeat_rate,
                    dp=self.dp,
                ))

    def adjust_data_num(self, factor: float):
        """调整所有用例的请求数（乘系数; 允许低于最小请求数）"""
        for case in self.test_cases:
            case.data_num_recommended = max(
                1,
                int(case.data_num_recommended * factor)
            )

    def adjust_concurrency(self, factor: float):
        """调整所有用例的并发数（乘系数）"""
        for case in self.test_cases:
            case.concurrency_recommended = max(
                1,
                int(case.concurrency_recommended * factor)
            )

    def adjust_single_case(self, idx: int, data_num: int = None, concurrency: int = None):
        """修改单个用例的参数 (请求数允许低于最小值, 由调用方提醒)"""
        if idx < 0 or idx >= len(self.test_cases):
            return
        case = self.test_cases[idx]
        if data_num is not None and data_num > 0:
            case.data_num_recommended = data_num
        if concurrency is not None and concurrency > 0:
            case.concurrency_recommended = max(1, concurrency)

    def delete_case(self, idx: int) -> bool:
        """删除用例"""
        if len(self.test_cases) <= 1:
            return False
        if 0 <= idx < len(self.test_cases):
            self.test_cases.pop(idx)
            return True
        return False

    def duplicate_case(self, idx: int) -> bool:
        """复制指定用例(含全部参数), 追加到列表末尾"""
        if 0 <= idx < len(self.test_cases):
            src = self.test_cases[idx]
            self.test_cases.append(TestCase(
                input_len=src.input_len,
                output_len=src.output_len,
                data_num_recommended=src.data_num_recommended,
                data_num_min=src.data_num_min,
                concurrency_recommended=src.concurrency_recommended,
                concurrency_max=src.concurrency_max,
                repeat_rate=src.repeat_rate,
                dp=src.dp,
                is_custom=True,
            ))
            return True
        return False

    def add_custom_case(self, input_len: int, output_len: int,
                        data_num: int = None, concurrency: int = None):
        """添加自定义用例 (校验长度不超模型最大上下文)"""
        if self.max_request_length > 0 and input_len + output_len > self.max_request_length:
            raise ValueError(
                f"输入+输出长度 ({input_len:,}+{output_len:,}={input_len + output_len:,}) "
                f"超过模型最大上下文 ({self.max_request_length:,}), "
                f"vLLM将返回Bad Request拒绝该请求")
        max_concurrency = max(1, int(self.total_kv_cache / (input_len + output_len)))
        min_data_num = max(
            int(self.total_kv_cache / input_len / self.repeat_rate) + 1,
            max_concurrency * 2
        )
        recommended_data_num = min_data_num * 2

        if data_num is None:
            data_num = recommended_data_num

        if concurrency is None:
            concurrency = max_concurrency
        else:
            concurrency = max(1, concurrency)

        self.test_cases.append(TestCase(
            input_len=input_len,
            output_len=output_len,
            data_num_recommended=data_num,
            data_num_min=min_data_num,
            concurrency_recommended=concurrency,
            concurrency_max=max_concurrency,
            repeat_rate=self.repeat_rate,
            dp=self.dp,
            is_custom=True,
        ))

    def get_kv_usage(self, case: TestCase) -> float:
        """计算KV cache使用率"""
        if self.total_kv_cache == 0:
            return 0.0
        return (case.concurrency_recommended *
                (case.input_len + case.output_len) /
                self.total_kv_cache * 100)

    def generate_commands(self) -> List[str]:
        """生成测试命令 (每次执行生成新的随机种子, 保证数据集可复现且不同轮次不同)"""
        import random
        seed = random.randint(1, 999999)
        commands = []
        for case in self.test_cases:
            cmd = (
                f"python3 aisbench_test.py "
                f"--prefix_test "
                f"--input_len {case.input_len} "
                f"--output_len {case.output_len} "
                f"--data_num {case.data_num_recommended} "
                f"--prefix_num {case.data_num_recommended} "
                f"--concurrency {case.concurrency_recommended} "
                f"--dataset_type prefix_cache "
                f"--repeat_rate {int(self.repeat_rate * 100)}% "
                f"--dp {self.dp} "
                f"--seed {seed}"
            )
            if self.request_rate > 0:
                cmd += f" --request_rate {self.request_rate}"
            commands.append(cmd)
        return commands

    def generate_shell_script(self, commands: List[str] = None) -> Tuple[str, str]:
        """
        生成测试shell脚本
        返回 (script_content, log_dir_name)
        """
        from datetime import datetime
        if commands is None:
            commands = self.generate_commands()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_dir_name = f"test_logs_{timestamp}"

        lines = []
        lines.append("#!/bin/bash")
        lines.append("")
        lines.append("# AISBench测试脚本 (由AISBench-Prefix-Tools生成)")
        lines.append(f"# 生成时间: {datetime.now()}")
        lines.append(f"# 单个DP组KV cache: {self.single_kv_cache:,} tokens")
        lines.append(f"# DP组数: {self.dp}")
        lines.append(f"# 总KV cache: {self.total_kv_cache:,} tokens")
        lines.append(f"# 前缀命中率: {self.repeat_rate*100:.0f}%")
        rate_str = "Burst" if self.request_rate == 0 else f"{self.request_rate} req/s"
        lines.append(f"# 请求发送速率: {rate_str}")
        lines.append("")
        lines.append("set -o pipefail")
        lines.append("")
        lines.append(f'LOG_DIR="./{log_dir_name}"')
        lines.append('mkdir -p "${LOG_DIR}"')
        lines.append("")

        lines.append("# ===== 预检查: 验证MODEL_PATH =====")
        lines.append('MODEL_PATH_VAL=$(python3 -c "import config; print(config.MODEL_PATH)" 2>/dev/null)')
        lines.append('if [ -z "$MODEL_PATH_VAL" ]; then')
        lines.append('    echo "错误: 无法从config.py读取MODEL_PATH，请检查config.py是否已正确保存" | tee -a "${LOG_DIR}/preflight.log"')
        lines.append('    exit 1')
        lines.append('fi')
        lines.append('if [ ! -d "$MODEL_PATH_VAL" ]; then')
        lines.append('    echo "错误: MODEL_PATH路径不存在: $MODEL_PATH_VAL" | tee -a "${LOG_DIR}/preflight.log"')
        lines.append('    echo "可能原因: 1)模型路径错误 2)Docker未正确挂载模型权重(挂载了不存在的宿主机路径会创建空目录)" | tee -a "${LOG_DIR}/preflight.log"')
        lines.append('    exit 1')
        lines.append('fi')
        lines.append('if [ ! -f "$MODEL_PATH_VAL/config.json" ]; then')
        lines.append('    echo "错误: $MODEL_PATH_VAL/config.json 不存在" | tee -a "${LOG_DIR}/preflight.log"')
        lines.append('    echo "模型权重可能未正确部署，Docker挂载可能创建了空目录" | tee -a "${LOG_DIR}/preflight.log"')
        lines.append('    exit 1')
        lines.append('fi')
        lines.append('echo "预检查通过: MODEL_PATH=$MODEL_PATH_VAL"')
        lines.append("")
        lines.append('FAIL_COUNT=0')
        lines.append("")

        for i, cmd in enumerate(commands, 1):
            case = self.test_cases[i-1]
            lines.append(f'echo "=========================================="')
            lines.append(f'echo "测试 #{i}: input_len={case.input_len}, output_len={case.output_len}"')
            lines.append(f'echo "开始时间: $(date \'+%Y-%m-%d %H:%M:%S\')"')
            lines.append(f'echo "=========================================="')
            lines.append("")
            log_name = f"test_{i}_{case.input_len}_{case.output_len}.log"
            lines.append(f'{cmd} 2>&1 | tee -a "${{LOG_DIR}}/{log_name}"')
            lines.append(f'TEST_EXIT=${{PIPESTATUS[0]}}')
            lines.append(f'if [ "$TEST_EXIT" -eq 0 ]; then')
            lines.append(f'    echo "[$(date \'+%Y-%m-%d %H:%M:%S\')] 测试 #{i} 成功"')
            lines.append(f'else')
            lines.append(f'    echo "[$(date \'+%Y-%m-%d %H:%M:%S\')] 测试 #{i} 失败 (exit_code=$TEST_EXIT)"')
            lines.append(f'    FAIL_COUNT=$((FAIL_COUNT + 1))')
            lines.append(f'fi')
            lines.append("")
            lines.append('sleep 2')
            lines.append("")

        lines.append('echo "=========================================="')
        lines.append('echo "所有测试完成！"')
        lines.append(f'echo "日志目录: ${{LOG_DIR}}"')
        lines.append('if [ "$FAIL_COUNT" -gt 0 ]; then')
        lines.append('    echo "失败测试数: $FAIL_COUNT"')
        lines.append('fi')
        lines.append('echo "=========================================="')
        lines.append("")
        lines.append("exit $FAIL_COUNT")

        return '\n'.join(lines), log_dir_name

    def get_summary(self) -> str:
        """获取测试摘要"""
        lines = []
        lines.append(f"单个DP组KV cache: {self.single_kv_cache:,} tokens")
        lines.append(f"DP组数: {self.dp}")
        lines.append(f"总KV cache: {self.total_kv_cache:,} tokens")
        lines.append(f"最大请求长度: {self.max_request_length:,}")
        lines.append(f"前缀命中率: {self.repeat_rate*100:.0f}%")
        rate_str = "Burst模式" if self.request_rate == 0 else f"{self.request_rate} req/s"
        lines.append(f"请求发送速率: {rate_str}")
        lines.append(f"测试用例数: {len(self.test_cases)}")
        return '\n'.join(lines)
