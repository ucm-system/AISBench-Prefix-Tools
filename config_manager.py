"""
配置管理器 - 生成和写入config.py配置文件
"""

from typing import Dict, Optional
from docker_manager import DockerManager


class ConfigManager:
    """管理aisbench_auto_tools_prefix的config.py配置"""

    CONFIG_TEMPLATE = """# -*- coding: utf-8 -*-
# AISBench 测试配置文件 (由AISBench-Prefix-Tools自动生成)

# 数据集文件夹路径，需可访问；选aisbench_auto_tools_prefix中包含GSM8k.jsonl数据集文件路径
DATASET_PATH = "{dataset_path}"

# aisbench 工作路径，默认: "/benchmark"。可通过命令 `pip show ais-bench-benchmark | grep 'Editable project location'` 查询
WORK_PATH = "{work_path}"

# 服务配置的模型名称。见3.1.1.4.1-部署单机推理环境中vllm serve命令的 --served-model-name 参数
MODEL_NAME = "{model_name}"
# 模型权重路径, 用于读取 tokenizer，例如 /mnt/models/DeepSeek-V4-Flash-w8a8-mtp/
MODEL_PATH = "{model_path}"
# 请求目的 IP。
HOST_IP = "{host_ip}"
# 请求目的端口。
HOST_PORT = "{host_port}"
#鉴权信息，若未开启保持为空即可
API_KEY = "{api_key}"

# 如果使用稳态测试请将该字段设置为 "stable_stage"
DEFAULT_PERFORMANCE_TEST = "{default_perf}"

# aisbench输出日志保存路径
OUTPUT_DIR = "{output_dir}"

# 各节点信息，格式为 ["{{ip}}:{{port}}"]
# 用于查询vllm metrics计算各个dp域的prefix cache命中率，不配置默认为HOST_IP:HOST_PORT
# PD分离场景请填写各个节点的IP和对应dp域的port
# POD_INFO = ["141.xx.xx.11:8000","141.xx.xx.12:8000"]
POD_INFO = {pod_info}
"""

    DEFAULT_CONFIG = {
        'dataset_path': '',
        'work_path': '/benchmark',
        'model_name': 'ds',
        'model_path': '/path/to/model',
        'host_ip': '127.0.0.1',
        'host_port': '8000',
        'api_key': '',
        'default_perf': 'default_perf',
        'output_dir': './outputs/default',
        'pod_info': '[]',
    }

    def __init__(self, docker: DockerManager):
        self.docker = docker

    def generate_config_content(self, config: Dict[str, str]) -> str:
        """
        生成config.py文件内容
        """
        merged = self.DEFAULT_CONFIG.copy()
        merged.update(config)

        # 确保DATASET_PATH默认为代码挂载路径
        if not merged.get('dataset_path'):
            merged['dataset_path'] = self.docker.code_mount_path

        # POD_INFO格式化
        pod_info = merged.get('pod_info', '[]')
        if isinstance(pod_info, list):
            pod_info = str(pod_info)
        if isinstance(pod_info, str) and not pod_info.strip().startswith('['):
            items = [s.strip() for s in pod_info.split(',') if s.strip()]
            pod_info = '[' + ', '.join(f'"{i}"' for i in items) + ']'

        merged['pod_info'] = pod_info

        return self.CONFIG_TEMPLATE.format(**merged)

    def write_config_to_container(self, config: Dict[str, str],
                                  config_filename: str = "config.py") -> bool:
        """
        将config.py直接写入容器内部工作区
        """
        if not self.docker.container_name:
            print("错误: 容器未创建，无法写入config.py")
            return False
        content = self.generate_config_content(config)
        container_path = f"{self.docker.code_mount_path}/{config_filename}"
        return self.docker.write_file_in_container(container_path, content)

    def read_config_from_container(self, config_filename: str = "config.py") -> Optional[str]:
        """读取容器内的config.py"""
        container_path = f"{self.docker.code_mount_path}/{config_filename}"
        return self.docker.read_file_in_container(container_path)

    def validate_config(self, config: Dict[str, str]) -> list:
        """
        验证配置项，返回错误信息列表
        """
        errors = []

        if not config.get('model_name'):
            errors.append("MODEL_NAME 不能为空")
        if not config.get('model_path'):
            errors.append("MODEL_PATH 不能为空")
        if not config.get('host_ip'):
            errors.append("HOST_IP 不能为空")
        if not config.get('host_port'):
            errors.append("HOST_PORT 不能为空")

        # 检查端口是否为数字
        port = config.get('host_port', '')
        if port:
            try:
                int(port)
            except ValueError:
                errors.append(f"HOST_PORT 必须为数字: {port}")

        # POD_INFO验证
        pod_info = config.get('pod_info', '')
        if isinstance(pod_info, str) and pod_info.strip():
            if pod_info.strip() not in ('[]', ''):
                cleaned = pod_info.replace('[', '').replace(']', '').replace('"', '').replace("'", '')
                for item in cleaned.split(','):
                    item = item.strip()
                    if item and ':' not in item:
                        errors.append(f"POD_INFO项格式应为 'ip:port': {item}")

        return errors
