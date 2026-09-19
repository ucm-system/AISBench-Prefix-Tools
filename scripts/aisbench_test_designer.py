#!/usr/bin/env python3
"""
交互式AISBench测试用例设计器 (简化版)
"""

import os
import sys
from typing import List, Dict, Optional, Tuple
import re

class Colors:
    """终端颜色配置"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class InteractiveTestCaseDesigner:
    def __init__(self):
        self.single_kv_cache: int = 0
        self.dp: int = 0
        self.total_kv_cache: int = 0
        self.max_request_length: int = 0
        self.test_cases: List[Dict] = []
        self.request_rate = 0  # 改名为 request_rate
        self.repeat_rate = 0.9
        
    def print_header(self, text: str):
        print(f"\n{Colors.HEADER}{'='*80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.HEADER}{text:^80}{Colors.END}")
        print(f"{Colors.HEADER}{'='*80}{Colors.END}\n")
    
    def print_info(self, text: str):
        print(f"{Colors.CYAN}ℹ {text}{Colors.END}")
    
    def print_success(self, text: str):
        print(f"{Colors.GREEN}✓ {text}{Colors.END}")
    
    def print_warning(self, text: str):
        print(f"{Colors.WARNING}⚠ {text}{Colors.END}")
    
    def print_error(self, text: str):
        print(f"{Colors.FAIL}✗ {text}{Colors.END}")
    
    def print_command(self, cmd: str):
        print(f"{Colors.CYAN}  {cmd}{Colors.END}")
    
    def get_input(self, prompt: str, default: Optional[str] = None, 
                  required: bool = True, validator=None) -> str:
        while True:
            if default:
                user_input = input(f"{Colors.BOLD}{prompt}{Colors.END} [{default}]: ").strip()
                if not user_input:
                    user_input = default
            else:
                user_input = input(f"{Colors.BOLD}{prompt}{Colors.END}: ").strip()
            
            if not user_input and required:
                self.print_warning("输入不能为空，请重新输入")
                continue
            
            if validator and user_input:
                is_valid, error_msg = validator(user_input)
                if not is_valid:
                    self.print_error(error_msg)
                    continue
            
            return user_input
    
    def get_int_input(self, prompt: str, default: Optional[int] = None,
                      min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
        def validator(value: str) -> Tuple[bool, str]:
            try:
                val = int(value)
                if min_val is not None and val < min_val:
                    return False, f"值必须 >= {min_val}"
                if max_val is not None and val > max_val:
                    return False, f"值必须 <= {max_val}"
                return True, ""
            except ValueError:
                return False, "请输入有效的整数"
        
        result = self.get_input(prompt, str(default) if default else None, 
                               validator=validator)
        return int(result)
    
    def get_float_input(self, prompt: str, default: Optional[float] = None,
                        min_val: Optional[float] = None, 
                        max_val: Optional[float] = None) -> float:
        def validator(value: str) -> Tuple[bool, str]:
            try:
                val = float(value)
                if min_val is not None and val < min_val:
                    return False, f"值必须 >= {min_val}"
                if max_val is not None and val > max_val:
                    return False, f"值必须 <= {max_val}"
                return True, ""
            except ValueError:
                return False, "请输入有效的数字"
        
        result = self.get_input(prompt, str(default) if default else None,
                               validator=validator)
        return float(result)
    
    def get_bool_input(self, prompt: str, default: bool = True) -> bool:
        default_str = "Y/n" if default else "y/N"
        result = self.get_input(f"{prompt} ({default_str})", 
                               "Y" if default else "N")
        return result.lower() in ['y', 'yes', 'true', '1', '']
    
    def step1_input_kv_cache(self):
        """步骤1：输入KV cache size"""
        self.print_header("步骤 1/5: 输入GPU KV Cache信息")
        
        self.print_info("请从vLLM日志中找到 'GPU KV cache size' 信息")
        self.print_info("示例: 'GPU KV cache size: 198,469 tokens'")
        self.print_info("")
        self.print_info("注意: 多DP部署时，每个DP组的KV cache size是相同的")
        self.print_info("      只需要输入单个DP组的值，程序会自动乘以DP数")
        self.print_info("")
        
        self.single_kv_cache = self.get_int_input(
            "请输入单个DP组的KV cache size (tokens)",
            min_val=1
        )
        self.print_success(f"单个DP组KV cache: {self.single_kv_cache:,} tokens")
        
        self.dp = self.get_int_input(
            "请输入DP组数 (data-parallel-size)",
            min_val=1
        )
        self.print_success(f"DP组数: {self.dp}")
        
        self.total_kv_cache = self.single_kv_cache * self.dp
        self.print_success(f"总KV cache tokens: {self.total_kv_cache:,} (单个DP组 × DP数 = {self.single_kv_cache:,} × {self.dp})")
        
        self.print_info("\n请从vLLM日志中找到 'Maximum concurrency for Y tokens per request' 信息")
        self.print_info("示例: 'Maximum concurrency for 32,768 tokens per request: 12×'")
        
        self.max_request_length = self.get_int_input(
            "请输入单条请求的最大长度 (tokens)",
            min_val=1
        )
        self.print_success(f"最大请求长度: {self.max_request_length:,}")
        
        input("\n按 Enter 继续...")
    
    def step2_select_input_lengths(self):
        """步骤2：选择输入长度"""
        self.print_header("步骤 2/5: 选择测试的输入长度")
        
        self.print_info(f"最大请求长度限制: {self.max_request_length:,} tokens")
        self.print_info("建议选择小于最大请求长度的典型值，如: 8192, 16384, 32768, 65536")
        
        preset_options = [8192, 16384, 32768, 65536, 131072]
        valid_presets = [l for l in preset_options if l < self.max_request_length]
        
        if valid_presets:
            print(f"\n{Colors.GREEN}推荐的预设值 (小于 {self.max_request_length:,}):{Colors.END}")
            for i, val in enumerate(valid_presets, 1):
                print(f"  {i}. {val:,}")
        else:
            self.print_warning(f"没有预设值小于 {self.max_request_length:,}，请自定义输入")
        
        print(f"\n{Colors.CYAN}输入方式:{Colors.END}")
        print("  1. 选择预设 (输入数字序号，多个用逗号分隔)")
        print("  2. 自定义输入 (每行一个值，空行结束)")
        
        choice = self.get_input("请选择 (1/2)", default="1")
        
        input_lengths = []
        if choice == "1" and valid_presets:
            selection = self.get_input(
                f"请选择预设 (输入序号，如: 1,2,3 或 1-3)",
                default="1,2,3"
            )
            selected = []
            for part in selection.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = part.split('-')
                    selected.extend(range(int(start)-1, int(end)))
                else:
                    selected.append(int(part)-1)
            
            for idx in selected:
                if 0 <= idx < len(valid_presets):
                    input_lengths.append(valid_presets[idx])
            
            if not input_lengths:
                self.print_warning("未选择有效预设，使用默认值")
                input_lengths = [16384, 32768]
        else:
            print("\n请输入输入长度 (tokens)，每行一个，空行结束:")
            while True:
                line = input("  ").strip()
                if not line:
                    break
                try:
                    val = int(line)
                    if val >= self.max_request_length:
                        self.print_warning(f"{val:,} >= 最大请求长度 {self.max_request_length:,}，跳过")
                    else:
                        input_lengths.append(val)
                except ValueError:
                    self.print_error(f"无效数字: {line}")
            
            if not input_lengths:
                self.print_warning("未选择任何输入长度，使用默认值: 16384, 32768")
                input_lengths = [16384, 32768]
        
        self.input_lengths = sorted(set(input_lengths))
        self.print_success(f"已选择 {len(self.input_lengths)} 个输入长度: {', '.join(f'{v:,}' for v in self.input_lengths)}")
        
        input("\n按 Enter 继续...")
    
    def step3_select_output_lengths(self):
        """步骤3：选择输出长度"""
        self.print_header("步骤 3/5: 选择测试的输出长度")
        
        self.print_info("参照业界测试标准，建议设置为 512 或 1024")
        
        preset_options = [128, 256, 512, 1024, 2048]
        
        print(f"\n{Colors.GREEN}预设值:{Colors.END}")
        for i, val in enumerate(preset_options, 1):
            print(f"  {i}. {val}")
        
        print(f"\n{Colors.CYAN}输入方式:{Colors.END}")
        print("  1. 选择预设 (输入数字序号，多个用逗号分隔)")
        print("  2. 自定义输入 (每行一个值，空行结束)")
        
        choice = self.get_input("请选择 (1/2)", default="1")
        
        output_lengths = []
        if choice == "1":
            selection = self.get_input(
                "请选择预设 (如: 3,4 表示 512,1024)",
                default="3,4"
            )
            for part in selection.split(','):
                part = part.strip()
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(preset_options):
                        output_lengths.append(preset_options[idx])
                except ValueError:
                    pass
            
            if not output_lengths:
                self.print_warning("使用默认值: 512, 1024")
                output_lengths = [512, 1024]
        else:
            print("\n请输入输出长度 (tokens)，每行一个，空行结束:")
            while True:
                line = input("  ").strip()
                if not line:
                    break
                try:
                    output_lengths.append(int(line))
                except ValueError:
                    self.print_error(f"无效数字: {line}")
            
            if not output_lengths:
                self.print_warning("使用默认值: 512, 1024")
                output_lengths = [512, 1024]
        
        self.output_lengths = sorted(set(output_lengths))
        self.print_success(f"已选择 {len(self.output_lengths)} 个输出长度: {', '.join(f'{v:,}' for v in self.output_lengths)}")
        
        input("\n按 Enter 继续...")
    
    def step4_set_repeat_rate(self):
        """步骤4：设置前缀命中率"""
        self.print_header("步骤 4/5: 设置前缀命中率 (repeat_rate)")
        
        self.print_info("前缀命中率表示请求中命中前缀缓存的比例")
        self.print_info("建议设置为 90% (0.9) 以模拟真实场景")
        
        self.repeat_rate = self.get_float_input(
            "请输入前缀命中率 (0.0 - 1.0)",
            default=0.9,
            min_val=0.0,
            max_val=1.0
        )
        
        self.print_success(f"前缀命中率: {self.repeat_rate*100:.0f}%")
        
        input("\n按 Enter 继续...")
    
    def step5_generate_recommendations(self):
        """步骤5：生成推荐的测试参数"""
        self.print_header("步骤 5/5: 生成推荐的测试参数")
        
        self.test_cases = []
        
        for input_len in self.input_lengths:
            for output_len in self.output_lengths:
                max_concurrency = int(self.total_kv_cache / (input_len + output_len) * 0.9)
                max_concurrency = max(1, max_concurrency)
                
                min_data_num = int(self.total_kv_cache / input_len / self.repeat_rate) + 1
                min_data_num = max(min_data_num, max_concurrency * 2)
                
                recommended_data_num = min_data_num * 2
                
                self.test_cases.append({
                    'input_len': input_len,
                    'output_len': output_len,
                    'data_num_recommended': recommended_data_num,
                    'data_num_min': min_data_num,
                    'concurrency_recommended': max_concurrency,
                    'concurrency_max': max_concurrency,
                    'repeat_rate': self.repeat_rate,
                    'dp': self.dp
                })
        
        self.print_test_cases()
        
        input("\n按 Enter 继续...")
    
    def print_test_cases(self):
        """打印测试用例表格"""
        if not self.test_cases:
            return
        
        print(f"\n{Colors.BOLD}生成的测试用例推荐参数:{Colors.END}")
        print("-" * 120)
        print(f"{'#':>3} {'Input':>12} {'Output':>12} {'请求数(推荐)':>14} {'请求数(最小)':>14} {'并发(推荐)':>14} {'KV使用率':>12}")
        print("-" * 120)
        
        for i, case in enumerate(self.test_cases, 1):
            kv_usage = (case['concurrency_recommended'] * 
                       (case['input_len'] + case['output_len']) / 
                       self.total_kv_cache * 100)
            print(f"{i:>3} {case['input_len']:>12,} {case['output_len']:>12,} "
                  f"{case['data_num_recommended']:>14,} {case['data_num_min']:>14,} "
                  f"{case['concurrency_recommended']:>14,} {kv_usage:>11.1f}%")
        
        print("-" * 120)
        
        print(f"\n{Colors.CYAN}参数设计依据:{Colors.END}")
        for i, case in enumerate(self.test_cases, 1):
            max_conc = self.total_kv_cache // (case['input_len'] + case['output_len'])
            print(f"\n{Colors.BOLD}用例 #{i}: Input={case['input_len']:,}, Output={case['output_len']:,}{Colors.END}")
            print(f"  • 请求数 ({case['data_num_recommended']:,}) = 最小请求数 × 2;  最小请求数 = floor(KV_cache({self.total_kv_cache:,}) / input_len({case['input_len']:,}) / repeat_rate({self.repeat_rate:.2f})) + 1 = {case['data_num_min']:,}")
            print(f"  • 并发数 ({case['concurrency_recommended']:,}) < KV_cache({self.total_kv_cache:,}) / (input_len({case['input_len']:,}) + output_len({case['output_len']:,})) = {max_conc}")
            print(f"  • KV cache使用率: {kv_usage:.1f}%")
    
    def step6_adjust_and_confirm(self):
        """步骤6：调整参数并确认"""
        self.print_header("调整参数并确认")
        
        while True:
            print(f"\n{Colors.BOLD}当前测试用例列表:{Colors.END}")
            self.print_test_cases()
            
            print(f"\n{Colors.CYAN}可用操作:{Colors.END}")
            print("  1. 修改所有用例的请求数 (乘系数)")
            print("  2. 修改所有用例的并发数 (乘系数)")
            print("  3. 修改单个用例的参数")
            print("  4. 设置请求发送速率 (每秒发送请求数)")
            print("  5. 删除某个用例")
            print("  6. 添加自定义用例")
            print("  7. 回到步骤2 (修改输入长度)")
            print("  8. 回到步骤3 (修改输出长度)")
            print("  9. 确认并生成测试命令")
            print("  0. 退出")
            
            choice = self.get_input("请选择操作", default="9")
            
            if choice == "0":
                print("退出程序")
                sys.exit(0)
            elif choice == "1":
                self.adjust_data_num()
            elif choice == "2":
                self.adjust_concurrency()
            elif choice == "3":
                self.adjust_single_case()
            elif choice == "4":
                self.set_request_rate()
            elif choice == "5":
                self.delete_case()
            elif choice == "6":
                self.add_custom_case()
            elif choice == "7":
                self.step2_select_input_lengths()
                self.step5_generate_recommendations()
            elif choice == "8":
                self.step3_select_output_lengths()
                self.step5_generate_recommendations()
            elif choice == "9":
                if self.confirm_and_generate():
                    break
            else:
                self.print_warning("无效选择，请重新输入")
    
    def adjust_data_num(self):
        """调整请求数"""
        factor = self.get_float_input(
            "请输入请求数的调整系数 (例如: 0.5 减半, 2 翻倍)",
            default=1.0,
            min_val=0.1
        )
        
        for case in self.test_cases:
            case['data_num_recommended'] = max(
                1,
                int(case['data_num_recommended'] * factor)
            )
            if case['data_num_recommended'] < case['data_num_min']:
                self.print_warning(
                    f"用例 Input={case['input_len']:,} 请求数 ({case['data_num_recommended']:,}) "
                    f"低于最小值 ({case['data_num_min']:,}), 低于该值不会在HBM之外的KV Cache缓存介质中命中"
                )
        
        self.print_success("已更新所有用例的请求数")
        self.print_test_cases()
    
    def adjust_concurrency(self):
        """调整并发数"""
        factor = self.get_float_input(
            "请输入并发数的调整系数 (例如: 0.5 减半, 2 翻倍)",
            default=1.0,
            min_val=0.1
        )
        
        for case in self.test_cases:
            case['concurrency_recommended'] = max(
                1,
                int(case['concurrency_recommended'] * factor)
            )
            case['concurrency_recommended'] = min(
                case['concurrency_recommended'],
                case['concurrency_max']
            )
        
        self.print_success("已更新所有用例的并发数")
        self.print_test_cases()
    
    def adjust_single_case(self):
        """修改单个用例"""
        self.print_test_cases()
        
        case_idx = self.get_int_input(
            f"请选择要修改的用例编号 (1-{len(self.test_cases)})",
            min_val=1,
            max_val=len(self.test_cases)
        ) - 1
        
        case = self.test_cases[case_idx]
        
        print(f"\n{Colors.BOLD}修改用例 #{case_idx + 1}:{Colors.END}")
        print(f"  输入长度: {case['input_len']:,}")
        print(f"  输出长度: {case['output_len']:,}")
        print(f"  当前请求数: {case['data_num_recommended']:,} (最小: {case['data_num_min']:,})")
        print(f"  当前并发数: {case['concurrency_recommended']:,} (最大: {case['concurrency_max']:,})")
        
        new_data_num = self.get_int_input(
            "新的请求数 (输入0保持当前值)",
            default=case['data_num_recommended'],
            min_val=0
        )
        if new_data_num > 0:
            if new_data_num < case['data_num_min']:
                self.print_warning(
                    f"请求数 ({new_data_num:,}) 低于最小值 ({case['data_num_min']:,}), "
                    f"低于该值不会在HBM之外的KV Cache缓存介质中命中"
                )
            case['data_num_recommended'] = new_data_num
        
        new_concurrency = self.get_int_input(
            "新的并发数 (输入0保持当前值)",
            default=case['concurrency_recommended'],
            min_val=0
        )
        if new_concurrency > 0:
            case['concurrency_recommended'] = min(new_concurrency, case['concurrency_max'])
        
        self.print_success("已更新用例")
        self.print_test_cases()
    
    def set_request_rate(self):
        """设置请求发送速率"""
        self.print_info("请求发送速率: 每秒发送的请求数")
        self.print_info("  - 默认值 0: 立即发送所有请求 (burst模式)")
        self.print_info("  - 正数: 按指定速率平滑发送请求")
        self.print_info("  - 建议: 对于大请求，可设置较低速率避免资源争抢")
        
        self.request_rate = self.get_int_input(
            "每秒发送请求数 (0表示立即发送所有请求)",
            default=0,
            min_val=0
        )
        
        if self.request_rate == 0:
            self.print_success("使用burst模式: 同时发送所有请求")
        else:
            total_requests = sum(c['data_num_recommended'] for c in self.test_cases)
            total_time = total_requests / self.request_rate
            self.print_success(f"发送速率: {self.request_rate} req/s")
            self.print_info(f"预计总请求数: {total_requests:,}, 预计总发送时间: {total_time:.1f}s")
        
        input("\n按 Enter 继续...")
    
    def delete_case(self):
        """删除用例"""
        self.print_test_cases()
        
        if len(self.test_cases) <= 1:
            self.print_warning("至少保留一个用例")
            return
        
        case_idx = self.get_int_input(
            f"请选择要删除的用例编号 (1-{len(self.test_cases)})",
            min_val=1,
            max_val=len(self.test_cases)
        ) - 1
        
        deleted = self.test_cases.pop(case_idx)
        self.print_warning(f"已删除用例: Input={deleted['input_len']:,}, Output={deleted['output_len']:,}")
        self.print_test_cases()
    
    def add_custom_case(self):
        """添加自定义用例"""
        self.print_header("添加自定义测试用例")
        
        input_len = self.get_int_input("输入长度 (tokens)", min_val=1)
        if input_len >= self.max_request_length:
            self.print_warning(f"输入长度 {input_len:,} 超过最大请求长度 {self.max_request_length:,}")
            if not self.get_bool_input("是否继续?", default=False):
                return
        
        output_len = self.get_int_input("输出长度 (tokens)", min_val=1)
        
        max_concurrency = max(1, int(self.total_kv_cache / (input_len + output_len) * 0.9))
        min_data_num = max(
            int(self.total_kv_cache / input_len / self.repeat_rate) + 1,
            max_concurrency * 2
        )
        recommended_data_num = min_data_num * 2

        self.print_info(f"推荐的请求数: {recommended_data_num:,} (最小: {min_data_num:,})")
        self.print_info(f"推荐的并发数: {max_concurrency:,}")

        data_num = self.get_int_input(
            "请求数",
            default=recommended_data_num,
            min_val=1
        )
        if data_num < min_data_num:
            self.print_warning(
                f"请求数 ({data_num:,}) 低于最小值 ({min_data_num:,}), "
                f"低于该值不会在HBM之外的KV Cache缓存介质中命中"
            )
        
        concurrency = self.get_int_input(
            "并发数",
            default=max_concurrency,
            min_val=1,
            max_val=max_concurrency
        )
        
        self.test_cases.append({
            'input_len': input_len,
            'output_len': output_len,
            'data_num_recommended': data_num,
            'data_num_min': min_data_num,
            'concurrency_recommended': concurrency,
            'concurrency_max': max_concurrency,
            'repeat_rate': self.repeat_rate,
            'dp': self.dp,
            'is_custom': True
        })
        
        self.print_success("已添加自定义用例")
        self.print_test_cases()
    
    def confirm_and_generate(self) -> bool:
        """确认并生成测试命令"""
        self.print_header("确认测试用例")
        
        print(f"\n{Colors.BOLD}测试配置摘要:{Colors.END}")
        print(f"  • 单个DP组KV cache: {self.single_kv_cache:,} tokens")
        print(f"  • DP组数: {self.dp}")
        print(f"  • 总KV cache: {self.total_kv_cache:,} tokens")
        print(f"  • 最大请求长度: {self.max_request_length:,}")
        print(f"  • 前缀命中率: {self.repeat_rate*100:.0f}%")
        print(f"  • 请求发送速率: {'Burst模式' if self.request_rate == 0 else f'{self.request_rate} req/s'}")
        print(f"  • 测试用例数: {len(self.test_cases)}")
        
        print(f"\n{Colors.BOLD}测试命令预览:{Colors.END}")
        commands = self.generate_commands()
        for i, cmd in enumerate(commands, 1):
            print(f"\n{Colors.BOLD}用例 #{i}:{Colors.END}")
            self.print_command(cmd)
        
        if self.get_bool_input("\n确认生成测试脚本?", default=True):
            self.generate_script(commands)
            return True
        else:
            self.print_info("已取消，继续调整")
            return False
    
    def generate_commands(self) -> List[str]:
        """生成测试命令"""
        commands = []
        for case in self.test_cases:
            cmd = (
                f"python3 aisbench_test.py "
                f"--prefix_test "
                f"--input_len {case['input_len']} "
                f"--output_len {case['output_len']} "
                f"--data_num {case['data_num_recommended']} "
                f"--prefix_num {case['data_num_recommended']} "
                f"--concurrency {case['concurrency_recommended']} "
                f"--dataset_type prefix_cache "
                f"--repeat_rate {int(self.repeat_rate * 100)}% "
                f"--dp {self.dp}"
            )
            if self.request_rate > 0:
                cmd += f" --request_rate {self.request_rate}"  # 改为 --request_rate
            commands.append(cmd)
        return commands
    
    def generate_script(self, commands: List[str]):
        """生成测试脚本"""
        timestamp = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
        script_name = f"run_aisbench_tests_{timestamp}.sh"
        
        with open(script_name, 'w') as f:
            f.write("#!/bin/bash\n\n")
            f.write("# 交互式生成的AISBench测试脚本\n")
            f.write(f"# 生成时间: {__import__('datetime').datetime.now()}\n")
            f.write(f"# 单个DP组KV cache: {self.single_kv_cache:,} tokens\n")
            f.write(f"# DP组数: {self.dp}\n")
            f.write(f"# 总KV cache: {self.total_kv_cache:,} tokens\n")
            f.write(f"# 前缀命中率: {self.repeat_rate*100:.0f}%\n")
            f.write(f"# 请求发送速率: {'Burst' if self.request_rate == 0 else f'{self.request_rate} req/s'}\n\n")
            
            f.write("set -e\n\n")
            
            f.write('LOG_DIR="./test_logs_$(date +%Y%m%d_%H%M%S)"\n')
            f.write('mkdir -p ${LOG_DIR}\n\n')
            
            for i, cmd in enumerate(commands, 1):
                case = self.test_cases[i-1] if i <= len(self.test_cases) else {}
                f.write(f'echo "=========================================="\n')
                f.write(f'echo "测试 #{i}: input_len={case.get("input_len", "N/A")}, output_len={case.get("output_len", "N/A")}"\n')
                f.write(f'echo "开始时间: $(date \'+%Y-%m-%d %H:%M:%S\')"\n')
                f.write(f'echo "=========================================="\n\n')
                f.write(f'{cmd} 2>&1 | tee -a ${{LOG_DIR}}/test_{case.get("input_len", "N/A")}_{case.get("output_len", "N/A")}.log\n\n')
                f.write(f'if [ $? -eq 0 ]; then\n')
                f.write(f'    echo "[$(date \'+%Y-%m-%d %H:%M:%S\')] 测试 #{i} 成功"\n')
                f.write(f'else\n')
                f.write(f'    echo "[$(date \'+%Y-%m-%d %H:%M:%S\')] 测试 #{i} 失败"\n')
                f.write(f'fi\n\n')
                f.write(f'sleep 2\n\n')
            
            f.write('echo "=========================================="\n')
            f.write('echo "所有测试完成！"\n')
            f.write(f'echo "日志目录: ${{LOG_DIR}}"\n')
            f.write('echo "=========================================="\n')
        
        os.chmod(script_name, 0o755)
        
        self.print_success(f"测试脚本已生成: {script_name}")
        self.print_info(f"执行命令: ./{script_name}")
        
        print(f"\n{Colors.BOLD}也可以直接复制以下命令执行:{Colors.END}")
        for i, cmd in enumerate(commands, 1):
            print(f"\n{Colors.GREEN}# 测试 {i}{Colors.END}")
            print(cmd)
    
    def run(self):
        """运行交互式流程"""
        try:
            self.print_header("AISBench 测试用例交互式设计器")
            
            self.print_info("本工具将引导您完成测试用例的设计")
            self.print_info("您可以根据需要调整每个参数")
            input("\n按 Enter 开始...")
            
            self.step1_input_kv_cache()
            self.step2_select_input_lengths()
            self.step3_select_output_lengths()
            self.step4_set_repeat_rate()
            self.step5_generate_recommendations()
            
            self.request_rate = 0
            
            self.step6_adjust_and_confirm()
            
            print(f"\n{Colors.GREEN}✓ 测试用例设计完成！{Colors.END}")
            
        except KeyboardInterrupt:
            print(f"\n\n{Colors.WARNING}用户中断{Colors.END}")
            sys.exit(0)
        except Exception as e:
            self.print_error(f"发生错误: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

def main():
    designer = InteractiveTestCaseDesigner()
    designer.run()

if __name__ == "__main__":
    main()