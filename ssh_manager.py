"""
SSH管理器 - 处理与远程执行机的SSH连接、命令执行、文件传输
"""

import os
import stat
import time
import paramiko
from i18n import tr, trf
from typing import Optional, Tuple, List, Callable


class SSHManager:
    """SSH连接管理器"""

    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self.host = ""
        self.port = 22
        self.username = ""
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, host: str, port: int, username: str,
                password: str = None, key_path: str = None,
                timeout: int = 10) -> Tuple[bool, str]:
        """
        连接到远程主机
        返回 (success, message)
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': host,
                'port': port,
                'username': username,
                'timeout': timeout,
            }

            if key_path:
                key_path = os.path.expanduser(key_path)
                if key_path.endswith('.pem') or 'rsa' in key_path:
                    pkey = paramiko.RSAKey.from_private_key_file(key_path)
                else:
                    pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
                connect_kwargs['pkey'] = pkey
            elif password:
                connect_kwargs['password'] = password
                connect_kwargs['look_for_keys'] = False
                connect_kwargs['allow_agent'] = False

            self.client.connect(**connect_kwargs)

            # 设置大窗口以提高传输速度
            transport = self.client.get_transport()
            transport.default_window_size = 2147483647  # SSH最大窗口
            transport.packetizer.MAX_PACKET_SIZE = 32768

            self.sftp = transport.open_sftp_client()
            self.host = host
            self.port = port
            self.username = username
            self._connected = True
            return True, trf("连接成功: {host}:{port}", host=host, port=port)
        except paramiko.AuthenticationException:
            return False, tr("认证失败，请检查用户名/密码/密钥")
        except paramiko.SSHException as e:
            return False, trf("SSH连接错误: {error}", error=e)
        except Exception as e:
            return False, trf("连接失败: {error}", error=e)

    def execute(self, command: str, timeout: int = 300) -> Tuple[int, str, str]:
        """
        执行远程命令
        返回 (return_code, stdout, stderr)
        """
        if not self._connected or not self.client:
            return -1, "", tr("未连接到远程主机")

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            return exit_code, out, err
        except Exception as e:
            return -1, "", str(e)

    def execute_with_callback(self, command: str,
                              callback: Callable[[str], None] = None,
                              timeout: int = 600) -> int:
        """
        执行命令并实时输出（通过回调函数）
        返回 exit_code
        """
        if not self._connected or not self.client:
            return -1

        try:
            transport = self.client.get_transport()
            channel = transport.open_session()
            channel.set_combine_stderr(True)
            channel.get_pty()
            channel.exec_command(command)

            while True:
                if channel.recv_ready():
                    data = channel.recv(4096).decode('utf-8', errors='replace')
                    if data and callback:
                        callback(data)
                if channel.exit_status_ready():
                    while channel.recv_ready():
                        data = channel.recv(4096).decode('utf-8', errors='replace')
                        if data and callback:
                            callback(data)
                    break
                time.sleep(0.1)

            return channel.exit_status
        except Exception as e:
            if callback:
                callback(f"\n[ERROR] {e}\n")
            return -1

    def upload_file(self, local_path: str, remote_path: str,
                    progress_callback: Callable[[int, int], None] = None) -> bool:
        """
        上传文件到远程主机（大窗口 + pipelined write，速度快数倍）
        """
        if not self._connected or not self.sftp:
            return False

        try:
            file_size = os.path.getsize(local_path)
            chunk_size = 256 * 1024  # 256KB chunks
            transferred = 0

            with open(local_path, 'rb') as fl:
                with self.sftp.file(remote_path, 'wb') as fr:
                    fr.set_pipelined(True)  # 开启管道写，大幅提升速度
                    while True:
                        data = fl.read(chunk_size)
                        if not data:
                            break
                        fr.write(data)
                        transferred += len(data)
                        if progress_callback:
                            progress_callback(transferred, file_size)
            return True
        except Exception as e:
            print(f"上传失败: {e}")
            return False

    def upload_file_in_background(self, local_path: str, remote_path: str,
                                   progress_callback: Callable[[int, int], None] = None,
                                   status_callback: Callable[[str], None] = None) -> bool:
        """
        后台上传文件，处理大文件
        """
        if not self._connected or not self.sftp:
            if status_callback:
                status_callback("未连接")
            return False

        try:
            file_size = os.path.getsize(local_path)
            if status_callback:
                status_callback(f"开始上传: {os.path.basename(local_path)} ({file_size / 1024 / 1024:.1f}MB)")

            ok = self.upload_file(local_path, remote_path, progress_callback)
            if status_callback:
                status_callback(f"上传完成: {remote_path}" if ok else "上传失败")
            return ok
        except Exception as e:
            if status_callback:
                status_callback(f"上传失败: {e}")
            return False

    def list_dir(self, path: str) -> List[dict]:
        """
        列出远程目录内容
        返回 [{"name": ..., "type": "dir"/"file", "size": ...}, ...]
        """
        if not self._connected or not self.sftp:
            return []

        result = []
        try:
            entries = self.sftp.listdir_attr(path)
            for entry in entries:
                entry_type = "dir" if stat.S_ISDIR(entry.st_mode) else "file"
                result.append({
                    'name': entry.filename,
                    'type': entry_type,
                    'size': entry.st_size if entry_type == "file" else 0,
                })
        except Exception as e:
            print(f"列出目录失败: {path}: {e}")
        return sorted(result, key=lambda x: (x['type'] != 'dir', x['name']))

    def list_dirs_only(self, path: str) -> List[str]:
        """只列出目录"""
        entries = self.list_dir(path)
        return [e['name'] for e in entries if e['type'] == 'dir']

    def file_exists(self, path: str) -> bool:
        """检查远程文件/目录是否存在"""
        if not self._connected or not self.sftp:
            return False
        try:
            self.sftp.stat(path)
            return True
        except IOError:
            return False

    def mkdir(self, path: str) -> bool:
        """创建远程目录"""
        if not self._connected or not self.sftp:
            return False
        try:
            self.sftp.mkdir(path)
            return True
        except Exception:
            return False

    def mkdir_p(self, path: str):
        """递归创建目录"""
        if not self._connected or not self.sftp:
            return
        parts = path.strip('/').split('/')
        current = ''
        for part in parts:
            current += '/' + part
            try:
                self.sftp.stat(current)
            except IOError:
                try:
                    self.sftp.mkdir(current)
                except Exception:
                    pass

    def write_file(self, remote_path: str, content: str) -> bool:
        """写入远程文件"""
        if not self._connected or not self.sftp:
            return False
        try:
            with self.sftp.open(remote_path, 'wb') as f:
                f.write(content.encode('utf-8'))
            return True
        except Exception as e:
            print(f"写入文件失败: {remote_path}: {e}")
            return False

    def read_file(self, remote_path: str) -> Optional[str]:
        """读取远程文件"""
        if not self._connected or not self.sftp:
            return None
        try:
            with self.sftp.open(remote_path, 'r') as f:
                return f.read().decode('utf-8')
        except Exception as e:
            print(f"读取文件失败: {e}")
            return None

    def disconnect(self):
        """断开连接"""
        try:
            if self.sftp:
                self.sftp.close()
                self.sftp = None
            if self.client:
                self.client.close()
                self.client = None
            self._connected = False
        except Exception:
            pass
