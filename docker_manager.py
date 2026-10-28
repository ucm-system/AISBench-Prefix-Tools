"""
Docker管理器 - 通过SSH管理远程Docker容器
"""

import re
import time
import os
import json
import tarfile
from datetime import datetime
from typing import Optional, Tuple, List, Callable
from ssh_manager import SSHManager


class DockerManager:
    """通过SSH管理Docker容器"""

    def __init__(self, ssh: SSHManager):
        self.ssh = ssh
        self.container_name: Optional[str] = None
        self.image_name: Optional[str] = None
        self.code_mount_path = "/benchmark/ais_bench/aisbench_auto_tools_prefix-main"
        self.code_host_path = ""
        self.remote_work_base = "/tmp/AISBench_Prefix_Tools"

    def check_docker_installed(self) -> Tuple[bool, str]:
        """检查Docker是否安装"""
        code, out, err = self.ssh.execute("docker --version 2>&1")
        if code == 0:
            return True, out.strip()
        return False, f"Docker未安装或不在PATH中: {err}"

    def work_dir_exists(self) -> bool:
        """检查远程工作目录是否已存在"""
        return self.ssh.file_exists(self.remote_work_base)

    def clean_work_dir(self, callback: Callable[[str], None] = None) -> bool:
        """清理远程工作目录"""
        if callback:
            callback(f"清理工作目录: {self.remote_work_base}\n")
        code, _, _ = self.ssh.execute(f"rm -rf {self.remote_work_base}")
        if code == 0:
            self.ssh.mkdir_p(self.remote_work_base)
            if callback:
                callback("  ✓ 清理完成\n")
            return True
        if callback:
            callback("  ✗ 清理失败\n")
        return False

    @staticmethod
    def get_image_name_from_tar(local_tar_path: str) -> Optional[str]:
        """
        从本地tar包中读取镜像名（不上传，不加载）
        通过读取tar内的 manifest.json 获取 RepoTags
        """
        try:
            with tarfile.open(local_tar_path, 'r') as tar:
                # 尝试读取 manifest.json
                for member in tar.getnames():
                    if member == 'manifest.json' or member.endswith('/manifest.json'):
                        f = tar.extractfile(member)
                        if f:
                            data = json.loads(f.read())
                            if isinstance(data, list) and data:
                                repo_tags = data[0].get('RepoTags', [])
                                if repo_tags:
                                    return repo_tags[0]
                        break
        except Exception as e:
            print(f"读取tar包manifest失败: {e}")
        return None

    def image_exists(self, image_name: str) -> bool:
        """检查远程是否已存在指定镜像"""
        # 精确匹配 Repository:Tag
        code, out, _ = self.ssh.execute(
            f"docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}}' | grep -ix '{image_name}'"
        )
        return bool(out.strip())

    def list_images(self) -> List[dict]:
        """列出执行机上已存在的Docker镜像

        返回 [{"name": "repository:tag", "id": "...", "created": "...", "size": "..."}]
        只返回可被用户直接选择的带名称镜像；无名镜像无法稳定判断是否为 AISBench。
        """
        code, out, err = self.ssh.execute("docker image ls --format '{{json .}}'")
        if code != 0:
            message = err.strip() or out.strip() or f"docker image ls 失败 (exit_code={code})"
            raise RuntimeError(message)

        images = []
        for line in out.splitlines():
            try:
                item = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            repository = str(item.get("Repository", "")).strip()
            tag = str(item.get("Tag", "")).strip()
            name = f"{repository}:{tag}" if tag else repository
            if not name or name.startswith("<none>"):
                continue
            images.append({
                "name": name,
                "id": str(item.get("ID", "")).strip(),
                "created": str(item.get("CreatedSince", "")).strip(),
                "size": str(item.get("Size", "")).strip(),
            })
        return images

    def load_image(self, remote_tar_path: str,
                   callback: Callable[[str], None] = None) -> Tuple[bool, str]:
        """
        从tar包加载Docker镜像
        返回 (success, image_name)
        """
        if callback:
            callback(f"正在加载镜像: docker load -i {remote_tar_path}\n")

        cmd = f"docker load -i {remote_tar_path}"
        exit_code = self.ssh.execute_with_callback(cmd, callback, timeout=600)

        if exit_code != 0:
            if callback:
                callback(f"\n镜像加载失败 (exit_code={exit_code})\n")
            return False, ""

        # 从输出中解析镜像名称
        code, out, err = self.ssh.execute(f"docker load -i {remote_tar_path} 2>&1 | tail -5")
        combined = out + err

        # 尝试匹配 "Loaded image: xxx" 或 "Loaded image ID: xxx"
        patterns = [
            r"Loaded image:\s*(\S+)",
            r"Loaded image ID:\s*(\S+)",
            r"Loaded image:\s*(.+)",
        ]

        image_name = None
        for pattern in patterns:
            match = re.search(pattern, combined)
            if match:
                image_name = match.group(1).strip()
                break

        if not image_name:
            # 列出所有镜像，取最新加载的
            code, out, err = self.ssh.execute(
                "docker images --format '{{.Repository}}:{{.Tag}} {{.CreatedSince}}' | head -20"
            )
            if callback:
                callback(f"\n可用镜像列表:\n{out}\n")
            return False, "无法自动识别镜像名称，请手动指定"

        self.image_name = image_name
        if callback:
            callback(f"\n识别到镜像: {image_name}\n")
        return True, image_name

    def generate_container_name(self) -> str:
        """生成唯一的容器名称"""
        timestamp = datetime.now().strftime('%m%d%H%M')
        return f"aisbench-test-{timestamp}"

    def container_exists(self, name: str) -> bool:
        """检查容器是否存在"""
        code, out, _ = self.ssh.execute(
            f"docker ps -a --filter 'name=^{name}$' --format '{{{{.Names}}}}'"
        )
        return name in out

    def remove_container(self, name: str, callback: Callable[[str], None] = None) -> bool:
        """停止并删除容器"""
        if callback:
            callback(f"停止并删除容器: {name}\n")
        self.ssh.execute(f"docker stop {name} 2>/dev/null")
        self.ssh.execute(f"docker rm {name} 2>/dev/null")
        return True

    def create_container(self, image_name: str, model_path: str,
                         code_host_path: str,
                         container_name: str = None,
                         callback: Callable[[str], None] = None) -> Tuple[bool, str]:
        """
        创建并启动Docker容器
        """
        if container_name is None:
            container_name = self.generate_container_name()

        # 如果容器已存在，先删除
        if self.container_exists(container_name):
            if callback:
                callback(f"容器 {container_name} 已存在，正在删除旧容器...\n")
            self.remove_container(container_name)

        cmd = (
            f"docker run -itd "
            f"--name {container_name} "
            f"--shm-size=1g "
            f"--net=host "
            f"-v {model_path}:{model_path} "
            f"-v {code_host_path}:{self.code_mount_path} "
            f"-w {self.code_mount_path} "
            f"{image_name} python3"
        )

        if callback:
            callback(f"创建容器命令:\n{cmd}\n\n")

        exit_code = self.ssh.execute_with_callback(cmd, callback, timeout=60)

        if exit_code != 0:
            return False, f"容器创建失败 (exit_code={exit_code})"

        # 验证容器是否运行
        time.sleep(2)
        code, out, _ = self.ssh.execute(
            f"docker ps --filter 'name=^{container_name}$' --format '{{{{.Status}}}}'"
        )
        if "Up" in out:
            self.container_name = container_name
            self.code_host_path = code_host_path
            if callback:
                callback(f"\n容器 {container_name} 已启动运行\n")
            return True, container_name
        else:
            return False, f"容器启动失败，状态: {out}"

    def upload_directory(self, local_dir: str, remote_dir: str,
                         callback: Callable[[str], None] = None) -> Tuple[bool, str]:
        """
        递归上传本地目录到远程目录 (SFTP)
        返回 (success, remote_dir 或 错误信息)
        """
        if not self.ssh.connected or not self.ssh.sftp:
            return False, "SSH未连接"

        local_dir = os.path.abspath(local_dir)
        if not os.path.isdir(local_dir):
            return False, f"本地目录不存在: {local_dir}"

        # 收集文件清单 (排除缓存/版本库文件)
        file_list = []
        for root, dirs, files in os.walk(local_dir):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
            for f in files:
                if f.endswith(('.pyc', '.pyo')):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, local_dir).replace('\\', '/')
                file_list.append((full, rel))

        total = len(file_list)
        if total == 0:
            return False, f"本地目录为空: {local_dir}"
        if callback:
            callback(f"  共 {total} 个文件待上传\n")

        self.ssh.mkdir_p(remote_dir)
        created_dirs = {remote_dir}

        done = 0
        for full, rel in file_list:
            # 确保远程父目录存在
            cur = remote_dir
            for part in rel.split('/')[:-1]:
                cur = f"{cur}/{part}"
                if cur not in created_dirs:
                    self.ssh.mkdir_p(cur)
                    created_dirs.add(cur)

            remote_path = f"{remote_dir}/{rel}"
            ok = self.ssh.upload_file(full, remote_path)
            done += 1
            if callback:
                callback(f"\r  上传中: {done}/{total}  {rel}")
            if not ok:
                if callback:
                    callback(f"\n  ✗ 上传失败: {rel}\n")
                return False, f"上传失败: {rel}"

        if callback:
            callback("\n")
        return True, remote_dir

    def extract_code_zip(self, remote_zip_path: str,
                         extract_dir: str = None,
                         callback: Callable[[str], None] = None) -> Tuple[bool, str]:
        """
        在远程主机上解压代码zip包
        返回 (success, extracted_path)
        """
        if extract_dir is None:
            extract_dir = os.path.dirname(remote_zip_path)

        # 确保目录存在
        self.ssh.execute(f"mkdir -p {extract_dir}")

        cmd = f"cd {extract_dir} && unzip -o {remote_zip_path}"
        if callback:
            callback(f"解压代码包: {cmd}\n")

        exit_code = self.ssh.execute_with_callback(cmd, callback, timeout=120)

        if exit_code != 0:
            # 尝试安装unzip
            if callback:
                callback("unzip不可用，尝试安装...\n")
            self.ssh.execute("yum install -y unzip 2>/dev/null || apt-get install -y unzip 2>/dev/null")
            exit_code = self.ssh.execute_with_callback(
                f"cd {extract_dir} && unzip -o {remote_zip_path}", callback, timeout=120
            )

        if exit_code != 0:
            return False, "解压失败"

        # 查找解压后的目录名
        zip_name = os.path.basename(remote_zip_path).replace('.zip', '')
        # GitHub zip解压后通常为主分支名-main
        possible_dirs = [zip_name, f"{zip_name}-main", "aisbench_auto_tools_prefix-main"]

        for d in possible_dirs:
            full_path = f"{extract_dir}/{d}"
            if self.ssh.file_exists(full_path):
                if callback:
                    callback(f"代码解压到: {full_path}\n")
                return True, full_path

        # 查找最新创建的目录
        code, out, _ = self.ssh.execute(f"ls -d {extract_dir}/*/ 2>/dev/null | head -5")
        dirs = [d.strip().rstrip('/') for d in out.strip().split('\n') if d.strip()]
        if dirs:
            return True, dirs[0]

        return False, "无法确定解压目录"

    def exec_in_container(self, command: str,
                         callback: Callable[[str], None] = None,
                         timeout: int = 600) -> int:
        """
        在容器内执行命令
        """
        if not self.container_name:
            if callback:
                callback("错误: 容器未创建\n")
            return -1

        cmd = f"docker exec -w {self.code_mount_path} {self.container_name} {command}"
        return self.ssh.execute_with_callback(cmd, callback, timeout=timeout)

    def container_is_running(self) -> bool:
        """检查容器是否在运行"""
        if not self.container_name:
            return False
        code, out, _ = self.ssh.execute(
            f"docker ps --filter 'name=^{self.container_name}$' --format '{{{{.Status}}}}'"
        )
        return "Up" in out

    def get_container_info(self) -> dict:
        """获取容器信息"""
        info = {'name': self.container_name, 'image': self.image_name, 'status': 'unknown'}
        if not self.container_name:
            return info

        code, out, _ = self.ssh.execute(
            f"docker ps -a --filter 'name=^{self.container_name}$' "
            f"--format '{{{{.Names}}}}|{{{{.Image}}}}|{{{{.Status}}}}|{{{{.CreatedAt}}}}'"
        )
        if out.strip():
            parts = out.strip().split('|')
            if len(parts) >= 4:
                info['name'] = parts[0]
                info['image'] = parts[1]
                info['status'] = parts[2]
                info['created'] = parts[3]
        return info

    def copy_from_container(self, container_path: str, host_path: str) -> bool:
        """从容器复制文件到宿主机"""
        if not self.container_name:
            return False
        cmd = f"docker cp {self.container_name}:{container_path} {host_path}"
        code, _, _ = self.ssh.execute(cmd, timeout=120)
        return code == 0

    def stop_and_remove(self, callback: Callable[[str], None] = None):
        """停止并删除容器"""
        if self.container_name:
            self.remove_container(self.container_name, callback)
            self.container_name = None

    # ============================================================
    #  测试脚本执行与日志下载
    # ============================================================

    def write_script(self, script_content: str, filename: str = "run_tests.sh") -> str:
        """
        将测试脚本写入到宿主机挂载目录（容器内可访问）
        返回容器内脚本路径
        """
        host_path = f"{self.code_host_path}/{filename}"
        self.ssh.write_file(host_path, script_content)
        self.ssh.execute(f"chmod +x {host_path}")
        return f"{self.code_mount_path}/{filename}"

    def run_script(self, script_name: str = "run_tests.sh",
                   callback: Callable[[str], None] = None,
                   timeout: int = 7200) -> int:
        """
        在容器内运行测试脚本（bash <script>）
        """
        container_script = f"{self.code_mount_path}/{script_name}"
        cmd = f"docker exec -w {self.code_mount_path} {self.container_name} bash {container_script}"
        return self.ssh.execute_with_callback(cmd, callback, timeout=timeout)

    def find_latest_log_dir(self) -> Optional[str]:
        """
        查找最新的 test_logs_* 目录（宿主机路径）
        返回宿主机路径，如 /tmp/AISBench_Prefix_Tools/aisbench_auto_tools_prefix-main/test_logs_20260909_200012
        """
        code, out, _ = self.ssh.execute(
            f"ls -dt {self.code_host_path}/test_logs_*/ 2>/dev/null | head -1"
        )
        result = out.strip().rstrip('/')
        if result:
            return result
        return None

    def download_logs(self, remote_log_dir: str, local_dir: str,
                      callback: Callable[[str], None] = None) -> List[str]:
        """
        从远程宿主机下载日志文件到本地Windows目录
        返回本地日志文件路径列表
        """
        if not self.ssh.connected or not self.ssh.sftp:
            if callback:
                callback("错误: SSH未连接\n")
            return []

        os.makedirs(local_dir, exist_ok=True)

        # 列出远程日志文件
        entries = self.ssh.list_dir(remote_log_dir)
        log_files = [e['name'] for e in entries if e['type'] == 'file' and e['name'].endswith('.log')]

        local_paths = []
        for fname in sorted(log_files):
            remote_path = f"{remote_log_dir}/{fname}"
            local_path = os.path.join(local_dir, fname)

            if callback:
                callback(f"下载: {fname}\n")

            ok = self.ssh.upload_file(remote_path, local_path) if False else self._sftp_download(remote_path, local_path)
            if ok:
                local_paths.append(local_path)
            else:
                if callback:
                    callback(f"  ✗ 下载失败: {fname}\n")

        if callback:
            callback(f"共下载 {len(local_paths)} 个日志文件到 {local_dir}\n")

        return local_paths

    def download_extra_files(self, filenames: List[str], local_dir: str,
                             callback: Callable[[str], None] = None) -> List[str]:
        """
        从代码目录(容器工作目录)下载指定附加文件
        如 aisbench_all.log / aisbench_result.csv
        返回本地文件路径列表
        """
        if not self.ssh.connected or not self.ssh.sftp:
            if callback:
                callback("错误: SSH未连接\n")
            return []

        os.makedirs(local_dir, exist_ok=True)

        local_paths = []
        for fname in filenames:
            remote_path = f"{self.code_host_path}/{fname}"
            if not self.ssh.file_exists(remote_path):
                if callback:
                    callback(f"跳过(不存在): {fname}\n")
                continue
            local_path = os.path.join(local_dir, fname)
            if callback:
                callback(f"下载: {fname}\n")
            if self._sftp_download(remote_path, local_path):
                local_paths.append(local_path)
            else:
                if callback:
                    callback(f"  ✗ 下载失败: {fname}\n")

        return local_paths

    def _sftp_download(self, remote_path: str, local_path: str) -> bool:
        """SFTP下载单个文件"""
        try:
            self.ssh.sftp.get(remote_path, local_path)
            return True
        except Exception as e:
            print(f"SFTP下载失败: {e}")
            return False
