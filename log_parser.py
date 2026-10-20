"""
日志解析器 - 从AISBench测试日志中提取第二次测试（全量数据集测试）的性能指标
移植自 extract_second_test_metrics.py，改为可被GUI直接调用的模块
"""

import re
import csv
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class LogParser:
    """解析单个AISBench测试日志文件"""

    def __init__(self, log_file_path: str):
        self.log_file = log_file_path
        self.content = ""
        self._load_log()

    def _load_log(self):
        """加载日志文件"""
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as f:
                self.content = f.read()
        except Exception as e:
            print(f"读取日志文件失败: {e}")

    def parse_second_test_json(self) -> Optional[Dict]:
        """提取第二次测试的JSON结果（output_len > 1）"""
        json_pattern = r"\{'current_time':\s*'[^']+',\s*'input_len':\s*[\d.]+,.*?\}"
        json_matches = list(re.finditer(json_pattern, self.content, re.DOTALL))

        if not json_matches:
            json_pattern = r'\{[^{]*"current_time"[^}]*\}'
            json_matches = list(re.finditer(json_pattern, self.content, re.DOTALL))

        if not json_matches:
            json_pattern = r"\{'current_time':.*?\}"
            json_matches = list(re.finditer(json_pattern, self.content, re.DOTALL))

        if not json_matches:
            return None

        for match in json_matches:
            json_str = match.group().replace("'", '"')
            try:
                result = json.loads(json_str)
                output_len = result.get('output_len', 0)
                if output_len > 1:
                    return result
            except json.JSONDecodeError:
                continue

        last_json = json_matches[-1].group().replace("'", '"')
        try:
            return json.loads(last_json)
        except json.JSONDecodeError:
            return None

    def parse_second_test_perf_table(self) -> Dict:
        """提取第二次测试的性能表格指标"""
        result = {}

        full_test_pos = self.content.find("[开始] 全量数据集测试")
        if full_test_pos == -1:
            full_test_pos = self.content.find("全量数据集测试")
        if full_test_pos == -1:
            return result

        after_content = self.content[full_test_pos:]
        perf_marker = "Performance Results of task"
        perf_pos = after_content.find(perf_marker)
        if perf_pos == -1:
            return result

        perf_content = after_content[perf_pos:]

        # TTFT
        ttft_pattern = r'TTFT\s+.*?total.*?([\d.]+)\s+ms.*?([\d.]+)\s+ms.*?([\d.]+)\s+ms'
        ttft_match = re.search(ttft_pattern, perf_content, re.DOTALL)
        if ttft_match:
            result['TTFT_avg'] = float(ttft_match.group(1))
            result['TTFT_min'] = float(ttft_match.group(2))
            result['TTFT_max'] = float(ttft_match.group(3))

        # TPOT
        tpot_pattern = r'TPOT\s+.*?total.*?([\d.]+)\s+ms.*?([\d.]+)\s+ms.*?([\d.]+)\s+ms'
        tpot_match = re.search(tpot_pattern, perf_content, re.DOTALL)
        if tpot_match:
            result['TPOT_avg'] = float(tpot_match.group(1))
            result['TPOT_min'] = float(tpot_match.group(2))
            result['TPOT_max'] = float(tpot_match.group(3))

        # E2EL
        e2el_pattern = r'E2EL\s+.*?total.*?([\d.]+)\s+ms.*?([\d.]+)\s+ms.*?([\d.]+)\s+ms'
        e2el_match = re.search(e2el_pattern, perf_content, re.DOTALL)
        if e2el_match:
            result['E2EL_avg'] = float(e2el_match.group(1))
            result['E2EL_min'] = float(e2el_match.group(2))
            result['E2EL_max'] = float(e2el_match.group(3))

        # Common Metrics
        common_marker = "Common Metric"
        common_pos = perf_content.find(common_marker)
        if common_pos != -1:
            common_content = perf_content[common_pos:]

            patterns = [
                (r'Prefill Token Throughput.*?([\d.]+)\s+token/s', 'prefill_token_throughput'),
                (r'Input Token Throughput.*?([\d.]+)\s+token/s', 'input_token_throughput'),
                (r'Output Token Throughput.*?([\d.]+)\s+token/s', 'output_throughput'),
                (r'Total Token Throughput.*?([\d.]+)\s+token/s', 'E2E_throughput'),
                (r'Request Throughput.*?([\d.]+)\s+req/s', 'qps'),
                (r'Concurrency\s+.*?([\d.]+)', 'cc'),
            ]
            for pattern, key in patterns:
                match = re.search(pattern, common_content, re.DOTALL)
                if match:
                    result[key] = float(match.group(1))

        return result

    def parse_hit_rates_second_test(self) -> Tuple[float, float]:
        """提取第二次测试的命中率 (hbm_hit_rate, external_hit_rate)"""
        hbm_hit_rate = 0.0
        external_hit_rate = 0.0

        full_test_pos = self.content.find("全量数据集测试完成，结果保存在aisbench_result.csv")
        if full_test_pos == -1:
            full_test_pos = self.content.find("全量数据集测试完成")
        if full_test_pos == -1:
            return self._parse_last_hit_rates()

        after_content = self.content[full_test_pos:]
        hit_summary_pos = after_content.find("Prefix cache hit summary")
        if hit_summary_pos == -1:
            return self._parse_last_hit_rates()

        hit_section = after_content[hit_summary_pos:]

        table_pattern = r'ALL_PODS\s+([\d.]+)%\s+[\d/]+\s+([\d.]+)%\s+[\d/]+'
        table_match = re.search(table_pattern, hit_section, re.DOTALL)
        if table_match:
            return float(table_match.group(1)), float(table_match.group(2))

        ext_match = re.search(r'external_hit_rate\s+([\d.]+)%', hit_section)
        if ext_match:
            external_hit_rate = float(ext_match.group(1))

        hbm_match = re.search(r'hbm_hit_rate\s+([\d.]+)%', hit_section)
        if hbm_match:
            hbm_hit_rate = float(hbm_match.group(1))

        return hbm_hit_rate, external_hit_rate

    def _parse_last_hit_rates(self) -> Tuple[float, float]:
        """解析最后一次出现的命中率"""
        hit_pattern = r"Prefix cache hit summary.*?ALL_PODS\s+([\d.]+)%\s+[\d/]+\s+([\d.]+)%\s+[\d/]+"
        matches = list(re.finditer(hit_pattern, self.content, re.DOTALL))
        if matches:
            last = matches[-1]
            return float(last.group(1)), float(last.group(2))
        return 0.0, 0.0

    def parse_basic_params(self) -> Dict:
        """从日志开头提取基本参数"""
        params = {}
        patterns = [
            (r'input token length:\s*(\d+)', 'input_len'),
            (r'output token length:\s*(\d+)', 'output_len'),
            (r'number of dataset:\s*(\d+)', 'total_req'),
            (r'concurrency:\s*(\d+)', 'max_cc'),
        ]
        for pattern, key in patterns:
            match = re.search(pattern, self.content)
            if match:
                params[key] = float(match.group(1))
        return params


# CSV字段定义
CSV_FIELDS = [
    'input_len', 'output_len', 'total_req', 'max_cc', 'cc',
    'hbm_hit_rate', 'external_hit_rate',
    'TTFT_avg', 'TTFT_min', 'TTFT_max', 'TTFT_P90',
    'TPOT_avg', 'TPOT_min', 'TPOT_max', 'TPOT_SLO_P90',
    'E2E_time',
    'output_throughput', 'E2E_throughput',
    'qps', 'qpm',
    'input_token_throughput', 'prefill_token_throughput',
    'E2EL_avg', 'E2EL_min', 'E2EL_max', 'E2EL_P90',
]


def result_to_csv_row(result: Dict) -> Dict:
    """将parse_single_log的结果转换为CSV行(字段与CSV_FIELDS对齐)"""
    return {
        'input_len': result.get('input_len', ''),
        'output_len': result.get('output_len', ''),
        'total_req': result.get('total_req', ''),
        'max_cc': result.get('max_cc', ''),
        'cc': result.get('cc', ''),
        'hbm_hit_rate': result.get('hbm_hit_rate', 0),
        'external_hit_rate': result.get('external_hit_rate', 0),
        'TTFT_avg': result.get('TTFT_avg', ''),
        'TTFT_min': result.get('TTFT_min', ''),
        'TTFT_max': result.get('TTFT_max', ''),
        'TTFT_P90': result.get('TTFT P90', ''),
        'TPOT_avg': result.get('TPOT_avg', ''),
        'TPOT_min': result.get('TPOT_min', ''),
        'TPOT_max': result.get('TPOT_max', ''),
        'TPOT_SLO_P90': result.get('TPOT SLO_P90', ''),
        'E2E_time': result.get('E2E_time', ''),
        'output_throughput': result.get('output_throughput', ''),
        'E2E_throughput': result.get('E2E_throughput', ''),
        'qps': result.get('qps', ''),
        'qpm': result.get('qpm', ''),
        'input_token_throughput': result.get('input_token_throughput', ''),
        'prefill_token_throughput': result.get('prefill_token_throughput', ''),
        'E2EL_avg': result.get('E2EL_avg', ''),
        'E2EL_min': result.get('E2EL_min', ''),
        'E2EL_max': result.get('E2EL_max', ''),
        'E2EL_P90': result.get('E2EL P90', ''),
    }


def parse_single_log(log_file: str) -> Optional[Dict]:
    """解析单个日志文件，提取第二次测试结果"""
    parser = LogParser(log_file)

    basic_params = parser.parse_basic_params()
    json_result = parser.parse_second_test_json()
    if not json_result:
        return None

    perf_result = parser.parse_second_test_perf_table()
    hbm_hit_rate, external_hit_rate = parser.parse_hit_rates_second_test()

    result = {}
    result.update(basic_params)
    result.update(json_result)
    result.update(perf_result)
    result['hbm_hit_rate'] = hbm_hit_rate
    result['external_hit_rate'] = external_hit_rate

    return result


def parse_log_directory(log_dir: str, output_csv: str,
                        progress_callback=None) -> List[Dict]:
    """
    处理日志目录中的所有 test_*.log 文件，提取指标并写入CSV

    参数:
        log_dir: 日志目录路径
        output_csv: 输出CSV文件路径
        progress_callback: 回调函数 callback(filename, success, result_dict)

    返回:
        解析结果列表
    """
    log_path = Path(log_dir)
    log_files = list(log_path.glob("test_*.log"))

    if not log_files:
        if progress_callback:
            progress_callback("(无日志文件)", False, None)
        return []

    if progress_callback:
        progress_callback(f"找到 {len(log_files)} 个日志文件", True, None)

    results = []

    for log_file in sorted(log_files):
        if progress_callback:
            progress_callback(f"解析: {log_file.name}", True, None)

        result = parse_single_log(str(log_file))

        if result:
            row = result_to_csv_row(result)
            results.append(row)

            if progress_callback:
                progress_callback(
                    f"  ✓ {log_file.name}: TTFT={row['TTFT_avg']}, "
                    f"TPOT={row['TPOT_avg']}, "
                    f"ext_hit={row['external_hit_rate']}%",
                    True, row
                )
        else:
            if progress_callback:
                progress_callback(f"  ✗ {log_file.name}: 解析失败", False, None)

    if results:
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(results)

    return results
