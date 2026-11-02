#!/usr/bin/env python3
"""多任务管理: 任务数据模型、后台执行器与生命周期管理

将原"创建任务"页面的 部署容器 → 写入config.py → 执行测试 流水线
提取为独立于UI的任务运行器, 支持:
- 多个任务并行执行, 每个任务拥有独立的SSH连接与容器
- 每个任务独立的本地日志文件(TaskLogBuffer处理\\r进度行并落盘)
- 任务元数据持久化到本地app数据目录(不含密码等敏感信息),
  程序重启后仍可查看历史任务、复制配置与清理容器
- 协作式取消: 设置取消标记, 测试执行阶段同时停止容器以中断长任务
"""

import json
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from config_manager import ConfigManager
from docker_manager import DockerManager
from i18n import tr, trf
from log_parser import parse_log_directory
from ssh_manager import SSHManager
from test_designer import TestCase, TestDesigner


class TaskCancelled(Exception):
    """任务被用户取消"""


class TaskStatus:
    """任务生命周期状态"""
    QUEUED = "queued"            # 已创建, 等待执行
    DEPLOYING = "deploying"      # 部署容器中
    CONFIGURING = "configuring"  # 写入配置中
    RUNNING = "running"          # 测试执行中
    COMPLETED = "completed"      # 执行完成
    FAILED = "failed"            # 执行失败
    CANCELLED = "cancelled"      # 用户取消
    INTERRUPTED = "interrupted"  # 程序重启导致的会话中断

    ALL = (QUEUED, DEPLOYING, CONFIGURING, RUNNING,
           COMPLETED, FAILED, CANCELLED, INTERRUPTED)
    ACTIVE = frozenset({QUEUED, DEPLOYING, CONFIGURING, RUNNING})
    TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED})


STATUS_LABELS = {
    TaskStatus.QUEUED: "排队中",
    TaskStatus.DEPLOYING: "部署中",
    TaskStatus.CONFIGURING: "配置中",
    TaskStatus.RUNNING: "执行中",
    TaskStatus.COMPLETED: "已完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.CANCELLED: "已取消",
    TaskStatus.INTERRUPTED: "已中断",
}


def status_label(status: str) -> str:
    """任务状态的本地化展示文本"""
    return tr(STATUS_LABELS.get(status, status))


STATUS_COLORS = {
    TaskStatus.QUEUED: "#6b7280",
    TaskStatus.DEPLOYING: "#2563eb",
    TaskStatus.CONFIGURING: "#2563eb",
    TaskStatus.RUNNING: "#2563eb",
    TaskStatus.COMPLETED: "#16a34a",
    TaskStatus.FAILED: "#dc2626",
    TaskStatus.CANCELLED: "#d97706",
    TaskStatus.INTERRUPTED: "#d97706",
}


def sanitize_task_name(name: str) -> str:
    """清理任务名, 使其可安全用于容器名与远程目录名"""
    s = re.sub(r'[^A-Za-z0-9_.-]+', '-', str(name).strip())
    s = s.strip('-_.')
    return (s or "task")[:40]


def auto_task_name(service_name: str) -> str:
    """默认任务名: 被测服务名_时间"""
    service = re.sub(r'[^A-Za-z0-9_.-]+', '-', str(service_name or "").strip())
    service = service.strip('-_.')[:20] or "ds"
    return f"{service}_{datetime.now():%Y%m%d_%H%M%S}"


def _get_bundled_code_dir() -> str:
    """内置aisbench代码目录 (兼容PyInstaller冻结环境)"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "aisbench_auto_tools_prefix")


class TaskLogBuffer:
    """任务日志缓冲: 终端语义处理\\r与ANSI转义, 完整行落盘并供UI轮询

    与界面版LiveLogHandler逻辑一致, 但不直接持有widget:
    - append(): 由工作线程调用, 立即处理并写入本地日志文件
    - poll():   由UI线程轮询, 返回自上次调用以来的新完整行与当前未完成行
    - finalize(): 任务结束时将未完成行落地
    """
    ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
    STATUS_RE = re.compile(
        r'^\s*(?:'
        r'POST=\d+'
        r'|Progress:.*\d+%'
        r'|Calculating performance details:.*\d+%'
        r'|\d{1,3}%\s*\|'
        r')'
    )

    def __init__(self, log_path):
        self.log_path = Path(log_path)
        self.lines: List[str] = []
        self._pending = ""
        self._pending_held = False
        self._raw = ""
        self._lock = threading.Lock()
        self._shown = 0
        self._fp = None
        self.finalized = False

    def open(self):
        """打开本地日志文件(追加模式)"""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.log_path, "a", encoding="utf-8", errors="replace")

    def close(self):
        with self._lock:
            self.finalize_locked()
            if self._fp:
                try:
                    self._fp.close()
                except OSError:
                    pass
                self._fp = None

    def append(self, text: str):
        with self._lock:
            self._raw += text
            self._process_locked()

    def poll(self) -> Tuple[List[str], str]:
        """UI轮询: 返回新增完整行与当前pending行"""
        with self._lock:
            new = self.lines[self._shown:]
            self._shown = len(self.lines)
            return new, self._pending

    def finalize(self):
        with self._lock:
            self.finalize_locked()

    def finalize_locked(self):
        """落地未完成内容(必须在锁内调用)

        raw尾部与pending是同一段未完成内容, 先删除pending再落地,
        避免重复(与LiveLogHandler.finalize语义一致)。
        """
        if self._raw:
            line = self._clean(self._raw)
            if line:
                self._delete_pending()
                self._commit(line)
            self._raw = ""
        if self._pending:
            self._commit(self._pending)
            self._pending = ""
            self._pending_held = False
        self.finalized = True

    # ---- 内部: 终端语义处理(必须在锁内调用) ----

    def _clean(self, s: str) -> str:
        s = self.ANSI_RE.sub('', s)
        if s.endswith('\r'):
            s = s[:-1]
        if '\r' in s:
            s = s.rsplit('\r', 1)[-1]
        return s

    @classmethod
    def _is_status(cls, s: str) -> bool:
        return bool(s) and bool(cls.STATUS_RE.match(s))

    def _commit(self, line: str):
        """完整行落地: 内存行列表 + 本地日志文件"""
        if not line:
            return
        self.lines.append(line)
        if self._fp is None:
            self.open()
        if self._fp:
            try:
                self._fp.write(line + "\n")
                self._fp.flush()
            except OSError:
                pass

    def _commit_pending(self):
        if self._pending:
            self._commit(self._pending)
        self._pending = ""
        self._pending_held = False

    def _delete_pending(self):
        self._pending = ""
        self._pending_held = False

    def _show_pending(self, s: str, held: bool = False):
        self._pending = s
        self._pending_held = held

    def _process_locked(self):
        if not self._raw:
            return
        segments = self._raw.split('\n')
        complete, tail = segments[:-1], segments[-1]
        self._raw = tail

        if complete and self._pending and not self._pending_held:
            self._delete_pending()

        for line in complete:
            cleaned = self._clean(line)
            if self._is_status(cleaned):
                if self._pending_held:
                    self._show_pending(cleaned, held=True)
                else:
                    self._commit_pending()
                    self._show_pending(cleaned, held=True)
            else:
                self._commit_pending()
                self._commit(cleaned)

        if tail:
            tail_cleaned = self._clean(tail)
            if self._pending and self._pending_held:
                if self._is_status(tail_cleaned):
                    self._show_pending(tail_cleaned, held=False)
                else:
                    self._commit_pending()
                    self._show_pending(tail_cleaned, held=False)
            else:
                self._show_pending(tail_cleaned, held=False)


@dataclass
class TaskInputs:
    """创建任务的完整输入快照(任务执行期间不再受界面修改影响)"""
    name: str = ""                    # 任务名, 留空自动: 服务名_时间
    image_mode: str = "existing"      # existing | upload
    selected_image: str = ""
    tar_path: str = ""
    code_source: str = "builtin"      # builtin | zip
    zip_path: str = ""
    model_path: str = ""
    work_dir_base: str = "/tmp/AISBench_Prefix_Tools"  # 临时部署基目录
    # vLLM服务连接参数(服务配置分区)
    model_name: str = "ds"
    host_ip: str = ""
    host_port: str = "8000"
    api_key: str = ""
    pod_info: str = ""
    # 测试参数快照
    kv_cache: str = ""
    dp: str = "1"
    max_req_len: str = ""
    repeat_rate: str = "0.9"
    request_rate: str = "0"
    input_lengths: List[int] = field(default_factory=list)
    output_lengths: List[int] = field(default_factory=list)
    cases: List[dict] = field(default_factory=list)
    local_output: str = ""

    def resolved_name(self) -> str:
        return self.name.strip() or auto_task_name(self.model_name)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskInputs":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


class Task:
    """一个可独立执行/取消/清理/删除的测试任务"""

    def __init__(self, task_id: str, inputs: TaskInputs,
                 ssh_config: Optional[dict], log_path):
        self.id = task_id
        self.inputs = inputs
        self.name = sanitize_task_name(inputs.resolved_name())
        self.display_name = inputs.resolved_name()
        self.ssh_config = ssh_config
        self.status = TaskStatus.QUEUED
        self.created_at = datetime.now()
        self.finished_at: Optional[datetime] = None
        self.cancel_flag = threading.Event()
        self.thread: Optional[threading.Thread] = None

        # 运行时资源
        self.ssh: Optional[SSHManager] = None
        self.docker: Optional[DockerManager] = None
        self.config_mgr: Optional[ConfigManager] = None
        self.designer: Optional[TestDesigner] = None
        self.container_name: str = ""
        self.deploy_work_dir: str = ""
        self.image_name: str = ""

        # 结果
        self.results: List[dict] = []
        self.csv_path: str = ""
        self.result_dir: str = ""
        self.error: str = ""
        self.resources_cleaned = False

        # 日志
        self.log_buffer = TaskLogBuffer(log_path)
        self._lock = threading.RLock()

    # ---- 状态与通知 ----

    def set_status(self, status: str, notify: Optional[Callable] = None):
        with self._lock:
            self.status = status
            if status in TaskStatus.TERMINAL and self.finished_at is None:
                self.finished_at = datetime.now()
        if notify:
            notify(self)

    def log(self, text: str):
        self.log_buffer.append(text)

    def check_cancel(self):
        """在阶段边界检查取消标记(由TaskRunner调用)"""
        if self.cancel_flag.is_set():
            raise TaskCancelled()

    def record(self) -> dict:
        """用于持久化的任务记录(不含密码等敏感信息)"""
        with self._lock:
            return {
                "id": self.id,
                "name": self.display_name,
                "status": self.status,
                "created_at": self.created_at.isoformat(timespec="seconds"),
                "finished_at": (self.finished_at.isoformat(timespec="seconds")
                                if self.finished_at else None),
                "container_name": self.container_name,
                "deploy_work_dir": self.deploy_work_dir,
                "image_name": self.image_name,
                "csv_path": self.csv_path,
                "result_dir": self.result_dir,
                "log_file": str(self.log_buffer.log_path),
                "error": self.error,
                "resources_cleaned": self.resources_cleaned,
                "inputs": self.inputs.to_dict(),
            }

    @classmethod
    def from_record(cls, rec: dict, log_dir: Path) -> "Task":
        """从持久化记录重建任务(历史会话, 不可恢复执行)"""
        inputs = TaskInputs.from_dict(rec.get("inputs", {}))
        inputs.name = rec.get("name", "")
        log_path = Path(rec.get("log_file") or
                        (log_dir / f"{sanitize_task_name(inputs.name)}.log"))
        task = cls(rec.get("id", uuid.uuid4().hex[:8]), inputs, None, log_path)
        task.display_name = rec.get("name", task.display_name)
        task.status = rec.get("status", TaskStatus.INTERRUPTED)
        if task.status in TaskStatus.ACTIVE:
            task.status = TaskStatus.INTERRUPTED
        if rec.get("created_at"):
            try:
                task.created_at = datetime.fromisoformat(rec["created_at"])
            except ValueError:
                pass
        if rec.get("finished_at"):
            try:
                task.finished_at = datetime.fromisoformat(rec["finished_at"])
            except ValueError:
                pass
        task.container_name = rec.get("container_name", "")
        task.deploy_work_dir = rec.get("deploy_work_dir", "")
        task.image_name = rec.get("image_name", "")
        task.csv_path = rec.get("csv_path", "")
        task.result_dir = rec.get("result_dir", "")
        task.error = rec.get("error", "")
        task.resources_cleaned = bool(rec.get("resources_cleaned"))
        return task

    def status_label(self) -> str:
        return status_label(self.status)


class TaskRunner:
    """任务执行器: 在后台线程中运行 部署 → 配置 → 测试 流水线"""

    def __init__(self, task: Task):
        self.task = task

    # ---- 入口 ----

    def run(self):
        task = self.task
        task.log(trf(
            "===== 创建任务 {name} ({time}) =====\n",
            name=task.display_name, time=task.created_at.strftime("%Y-%m-%d %H:%M:%S")))
        try:
            self._connect_ssh()
            self._deploy()
            self._configure()
            self._run_tests()
            task.set_status(TaskStatus.COMPLETED)
            task.log(tr("\n===== 任务执行完成 =====\n"))
        except TaskCancelled:
            task.error = tr("用户取消")
            task.set_status(TaskStatus.CANCELLED)
            self._mark_container_abnormal()
            task.log(tr("\n===== 任务已取消 =====\n"))
        except Exception as exc:  # noqa: BLE001 - 后台线程兜底记录
            task.error = str(exc)
            task.set_status(TaskStatus.FAILED)
            self._mark_container_abnormal()
            task.log(trf("\n===== 任务失败: {error} =====\n", error=task.error))
        finally:
            task.log_buffer.finalize()
            if task.ssh and task.ssh.connected:
                try:
                    task.ssh.disconnect()
                except Exception:
                    pass

    def _connect_ssh(self):
        task = self.task
        cfg = task.ssh_config or {}
        task.log(tr("[连接] 建立任务独立SSH连接...\n"))
        task.ssh = SSHManager()
        ok, msg = task.ssh.connect(
            host=cfg.get("host", ""),
            port=int(cfg.get("port", 22)),
            username=cfg.get("username", ""),
            password=cfg.get("password"),
            key_path=cfg.get("key_path"),
        )
        if not ok:
            raise RuntimeError(trf("SSH连接失败: {msg}", msg=msg))
        task.docker = DockerManager(task.ssh)
        task.log(trf("  ✓ {msg}\n", msg=msg))
        task.check_cancel()

    def _mark_container_abnormal(self):
        """取消/失败时把容器内测试状态标记为异常终止"""
        task = self.task
        if task.docker and task.container_name:
            try:
                task.docker.set_test_state(
                    task.docker.TEST_STATE_ABNORMAL,
                    callback=lambda t: task.log(t))
            except Exception:
                pass

    # ---- 阶段1: 部署 ----

    def _deploy(self):
        task = self.task
        inp = task.inputs
        task.set_status(TaskStatus.DEPLOYING)

        # 每个任务在基目录下使用独立临时子目录, 互不干扰
        base = inp.work_dir_base.strip().rstrip("/") or "/tmp/AISBench_Prefix_Tools"
        task.deploy_work_dir = (
            f"{base}/task_{task.name}_{datetime.now():%m%d%H%M%S}")
        task.docker.remote_work_base = task.deploy_work_dir

        task.log(trf("[部署] 使用临时部署目录: {dir}\n", dir=task.deploy_work_dir))

        task.log(tr("[1/5] 检查Docker环境...\n"))
        ok, msg = task.docker.check_docker_installed()
        if not ok:
            raise RuntimeError(tr(msg))
        task.log(trf("  ✓ {message}\n", message=tr(msg)))
        task.check_cancel()

        task.ssh.mkdir_p(task.deploy_work_dir)

        # 准备镜像
        task.log(tr("[2/5] 准备AISBench镜像...\n"))
        image_name = self._prepare_image(inp)
        task.image_name = image_name
        task.docker.image_name = image_name
        task.check_cancel()

        # 暂存代码
        extracted_path = self._stage_code(inp)
        task.check_cancel()

        # 创建容器(仅挂载模型路径)
        task.log(tr("[3/5] 创建并启动容器...\n"))
        task.container_name = (
            f"aisbench-test-{task.name}-{time.strftime('%m%d%H%M%S')}")
        ok, msg = task.docker.create_container(
            image_name, inp.model_path, task.container_name,
            callback=lambda t: task.log(t))
        if not ok:
            raise RuntimeError(tr(msg))
        task.log(trf("  ✓ 容器 {container} 已启动\n", container=task.container_name))
        task.docker.set_test_state(
            task.docker.TEST_STATE_INITIALIZED,
            container_name=task.container_name,
            callback=lambda t: task.log(t))
        task.check_cancel()

        # 导入代码并清理宿主机暂存目录
        task.log(tr("[4/5] 导入测试代码到容器...\n"))
        ok, msg = task.docker.copy_code_into_container(
            extracted_path, callback=lambda t: task.log(t))
        if not ok:
            raise RuntimeError(tr(msg))

        task.log(tr("[5/5] 清理宿主机临时目录...\n"))
        task.docker.remove_work_dir(callback=lambda t: task.log(t))
        task.log(trf("  ✓ 部署完成! 代码工作区: {path} (容器内)\n",
                     path=task.docker.code_mount_path))

        task.config_mgr = ConfigManager(task.docker)

    def _prepare_image(self, inp: TaskInputs) -> str:
        task = self.task
        if inp.image_mode == "existing" and inp.selected_image:
            if not task.docker.image_exists(inp.selected_image):
                raise RuntimeError(trf("镜像不存在: {image}", image=inp.selected_image))
            task.log(trf("  ✓ 复用执行机已有镜像: {image}\n", image=inp.selected_image))
            return inp.selected_image

        tar = inp.tar_path
        if not os.path.isfile(tar):
            raise RuntimeError(trf("镜像tar包不存在: {path}", path=tar))
        tar_name = os.path.basename(tar)

        # 从本地tar包预读镜像名(不上传)
        image_name = DockerManager.get_image_name_from_tar(tar)
        if image_name and task.docker.image_exists(image_name):
            task.log(trf("  ✓ 镜像已存在, 跳过上传: {image}\n", image=image_name))
            return image_name

        if image_name:
            task.log(trf("  镜像 {image} 不存在, 需要上传并加载\n", image=image_name))
        else:
            task.log(tr("  无法从tar包预读镜像名, 将上传后由docker load识别\n"))

        tar_size = os.path.getsize(tar)
        task.log(trf("  上传镜像tar包 ({size}MB)...\n", size=tar_size // 1024 // 1024))
        remote_tar = f"{task.deploy_work_dir}/{tar_name}"

        def _upload_progress(transferred, total):
            pct = transferred * 100 // total if total > 0 else 0
            task.log(trf("\r  上传中: {transferred}MB / {total}MB ({percent}%)",
                         transferred=transferred // 1024 // 1024,
                         total=total // 1024 // 1024, percent=pct))

        ok = task.ssh.upload_file(tar, remote_tar, _upload_progress)
        task.log("\n")
        if not ok:
            raise RuntimeError(tr("镜像上传失败"))
        task.log(tr("  ✓ 镜像上传完成\n"))
        task.check_cancel()

        task.log(tr("  加载Docker镜像...\n"))
        ok, image_name = task.docker.load_image(
            remote_tar, callback=lambda t: task.log(t))
        if not ok:
            raise RuntimeError(trf("镜像加载失败: {image}", image=image_name or ""))
        task.log("\n")
        return image_name

    def _stage_code(self, inp: TaskInputs) -> str:
        task = self.task
        if inp.code_source == "builtin":
            task.log(tr("  暂存内置测试代码...\n"))
            code_dir = _get_bundled_code_dir()
            if not os.path.isdir(code_dir):
                raise RuntimeError(trf(
                    "未找到内置测试代码目录: {path}", path=code_dir))
            target = f"{task.deploy_work_dir}/aisbench_auto_tools_prefix-main"
            ok, msg = task.docker.upload_directory(
                code_dir, target, callback=lambda t: task.log(t))
            if not ok:
                raise RuntimeError(tr(msg))
            return target

        zipf = inp.zip_path
        if not os.path.isfile(zipf):
            raise RuntimeError(trf("代码zip包不存在: {path}", path=zipf))
        task.log(tr("  暂存并解压代码zip包...\n"))
        zip_name = os.path.basename(zipf)
        remote_zip = f"{task.deploy_work_dir}/{zip_name}"
        ok = task.ssh.upload_file(zipf, remote_zip)
        if not ok:
            raise RuntimeError(tr("代码包上传失败"))
        ok, extracted = task.docker.extract_code_zip(
            remote_zip, task.deploy_work_dir,
            callback=lambda t: task.log(t))
        if not ok or not extracted:
            raise RuntimeError(tr("代码包解压失败"))
        return extracted

    # ---- 阶段2: 配置 ----

    def _configure(self):
        task = self.task
        inp = task.inputs
        task.set_status(TaskStatus.CONFIGURING)

        host_ip = (inp.host_ip or "").strip() or (task.ssh_config or {}).get("host", "")
        config = {
            'model_name': inp.model_name.strip() or 'ds',
            'model_path': inp.model_path,
            'host_ip': host_ip,
            'host_port': str(inp.host_port or '8000'),
            'api_key': (inp.api_key or '').strip(),
            'dataset_path': task.docker.code_mount_path,
            'work_path': '/benchmark',
            'default_perf': 'default_perf',
            'output_dir': './outputs/default',
            'pod_info': (inp.pod_info or '').strip(),
        }

        task.log(tr("[配置] 自动写入config.py到容器...\n"))
        errors = task.config_mgr.validate_config(config)
        if errors:
            raise RuntimeError(tr("配置校验失败:\n") + "".join(f"  {e}\n" for e in errors))
        if not task.config_mgr.write_config_to_container(config):
            raise RuntimeError(tr("config.py写入失败"))

        read_back = task.config_mgr.read_config_from_container()
        if read_back is None:
            task.log(tr("  ⚠ config.py已写入, 但回读验证失败(不影响继续执行)\n"))
            return

        saved = TaskRunner._parse_config_content(read_back)
        for key_field in ('MODEL_PATH', 'MODEL_NAME', 'HOST_IP', 'HOST_PORT', 'DATASET_PATH'):
            gui_val = str(config.get(key_field.lower(), ''))
            saved_val = saved.get(key_field, '')
            if gui_val and saved_val and gui_val != saved_val:
                raise RuntimeError(trf(
                    "config.py写入后回读不一致: {field} 界面={gui} 容器={container}",
                    field=key_field, gui=gui_val, container=saved_val))

        task.log(trf("  ✓ config.py已写入并验证一致\n"
                     "    MODEL_PATH={model_path}  MODEL_NAME={model_name}  "
                     "HOST={host_ip}:{host_port}\n",
                     model_path=config['model_path'],
                     model_name=config['model_name'],
                     host_ip=config['host_ip'],
                     host_port=config['host_port']))
        task.check_cancel()

    @staticmethod
    def _parse_config_content(content: str) -> dict:
        values = {}
        for match in re.finditer(r'^(\w+)\s*=\s*"([^"]*)"', content, re.MULTILINE):
            values[match.group(1)] = match.group(2)
        pod_match = re.search(r'^POD_INFO\s*=\s*(.+)$', content, re.MULTILINE)
        if pod_match:
            values['POD_INFO'] = pod_match.group(1).strip()
        return values

    # ---- 阶段3: 测试执行 ----

    def _build_designer(self) -> TestDesigner:
        """从任务输入快照重建测试设计器(用例等执行期数据固定)"""
        inp = self.task.inputs
        d = TestDesigner()
        d.set_kv_cache_info(
            int(inp.kv_cache or 0), int(inp.dp or 1), int(inp.max_req_len or 0))
        d.set_repeat_rate(float(inp.repeat_rate or 0.9))
        d.set_request_rate(float(inp.request_rate or 0))
        d.input_lengths = list(inp.input_lengths or [])
        d.output_lengths = list(inp.output_lengths or [])
        d.test_cases = [TestCase(**{k: v for k, v in c.items()
                                    if k in TestCase.__dataclass_fields__})
                        for c in (inp.cases or [])]
        return d

    def _run_tests(self):
        task = self.task
        inp = task.inputs
        task.set_status(TaskStatus.RUNNING)
        task.designer = self._build_designer()

        # 阶段0: 预检查模型路径
        task.log(tr("[测试] 预检查: 验证容器内MODEL_PATH...\n"))
        model_ok, model_msg = self._check_model_path()
        if not model_ok:
            raise RuntimeError(model_msg)
        task.log(trf("  ✓ {msg}\n", msg=model_msg))
        task.check_cancel()

        # 阶段1: 生成脚本
        task.log(tr("[测试] 生成测试脚本...\n"))
        script_content, log_dir_name = task.designer.generate_shell_script()
        task.log(trf("  日志目录名: {name}\n", name=log_dir_name))

        # 阶段2: 写入并运行
        task.log(tr("[测试] 写入测试脚本到容器并执行 (可能耗时较长)...\n"))
        container_script = task.docker.write_script(script_content)
        if not container_script:
            raise RuntimeError(tr("无法写入测试脚本到容器"))
        task.docker.set_test_state(
            task.docker.TEST_STATE_RUNNING, callback=lambda t: task.log(t))

        exit_code = task.docker.run_script(
            "run_tests.sh", callback=lambda t: task.log(t), timeout=7200)

        if task.cancel_flag.is_set():
            raise TaskCancelled()
        if exit_code != 0:
            task.docker.set_test_state(
                task.docker.TEST_STATE_ABNORMAL, callback=lambda t: task.log(t))
            task.log(trf("\n  ⚠ 部分测试失败 (exit_code={code}), 继续下载日志排查\n",
                         code=exit_code))
        else:
            task.docker.set_test_state(
                task.docker.TEST_STATE_COMPLETED, callback=lambda t: task.log(t))
            task.log(tr("\n  ✓ 测试脚本执行完成\n"))

        # 阶段3: 下载日志
        task.log(tr("[测试] 下载测试日志到本地...\n"))
        container_log_dir = task.docker.find_latest_log_dir() or \
            f"{task.docker.code_mount_path}/{log_dir_name}"
        task.log(trf("  容器内日志目录: {dir}\n", dir=container_log_dir))

        local_log_dir = os.path.join(inp.local_output, log_dir_name)
        os.makedirs(local_log_dir, exist_ok=True)
        local_files = task.docker.download_logs(
            container_log_dir, local_log_dir, callback=lambda t: task.log(t))
        extra = task.docker.download_extra_files(
            ["aisbench_all.log", "aisbench_result.csv"], local_log_dir,
            callback=lambda t: task.log(t))
        if extra:
            task.log(trf("  ✓ 已下载附加文件: {names}\n",
                         names=", ".join(os.path.basename(p) for p in extra)))
        if not local_files:
            raise RuntimeError(tr("未下载到任何日志文件"))
        task.log(trf("  ✓ 已下载 {count} 个日志文件到 {dir}\n",
                     count=len(local_files), dir=local_log_dir))
        task.result_dir = local_log_dir

        # 阶段4: 解析CSV
        task.log(tr("[测试] 解析日志生成CSV结果...\n"))
        csv_path = os.path.join(local_log_dir, f"results_{log_dir_name}.csv")
        results = parse_log_directory(
            local_log_dir, csv_path,
            progress_callback=lambda msg, ok, row: task.log(msg + "\n"))
        task.csv_path = csv_path
        task.results = results

        if results:
            task.log(trf("✓ 测试完成! 共 {count} 条结果\n", count=len(results)))
            task.log(trf("  CSV文件: {path}\n", path=csv_path))
            task.log(trf("  日志目录: {dir}\n", dir=local_log_dir))
        else:
            task.log(tr("  ✗ 未能从日志中提取到有效结果\n"))
            preflight = os.path.join(local_log_dir, "preflight.log")
            if os.path.exists(preflight):
                try:
                    with open(preflight, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read().strip()
                    if content:
                        task.log(trf("  预检查错误信息:\n{content}\n", content=content))
                except OSError:
                    pass

    def _check_model_path(self) -> Tuple[bool, str]:
        task = self.task
        check_script = (
            'import config, os, sys\n'
            'p = config.MODEL_PATH\n'
            'if not os.path.isdir(p):\n'
            '    print(f"FAIL: MODEL_PATH不存在: {p}")\n'
            '    sys.exit(1)\n'
            'if not os.path.isfile(os.path.join(p, "config.json")):\n'
            '    print(f"FAIL: {p}/config.json 不存在")\n'
            '    sys.exit(1)\n'
            'print(f"OK: MODEL_PATH={p}")\n'
        )
        path = f"{task.docker.code_mount_path}/_check_model_path.py"
        if not task.docker.write_file_in_container(path, check_script):
            return False, tr("无法写入预检查脚本到容器")
        cmd = (f"docker exec -w {task.docker.code_mount_path} "
               f"{task.container_name} python3 _check_model_path.py")
        code, out, err = task.ssh.execute(cmd)
        task.docker.remove_file_in_container(path)
        out = out.strip()
        if code == 0 and "OK:" in out:
            return True, out
        return False, out or (err.strip() if err else tr("未知错误"))


class TaskManager:
    """任务注册表与生命周期管理, 元数据持久化到本地app数据目录"""

    INDEX_VERSION = 1

    def __init__(self, data_dir=None):
        if data_dir is None:
            from settings_manager import app_data_dir
            data_dir = app_data_dir()
        self.data_dir = Path(data_dir)
        self.log_dir = self.data_dir / "logs"
        self.index_path = self.data_dir / "tasks.json"
        self.tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        # UI变更回调(在工作线程触发, UI侧需自行调度到主线程)
        self.on_change: Optional[Callable[[Task], None]] = None
        self.load()

    # ---- 持久化 ----

    def load(self):
        """加载历史任务记录(运行中任务标记为已中断)"""
        with self._lock:
            self.tasks.clear()
            if not self.index_path.exists():
                return
            try:
                with self.index_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                for rec in data.get("tasks", []):
                    task = Task.from_record(rec, self.log_dir)
                    self.tasks[task.id] = task
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                pass

    def save_index(self):
        """持久化任务索引(失败静默, 不影响主流程)"""
        with self._lock:
            data = {
                "version": self.INDEX_VERSION,
                "tasks": [t.record() for t in self.tasks.values()],
            }
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self.index_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _notify(self, task: Task):
        if self.on_change:
            try:
                self.on_change(task)
            except Exception:
                pass

    # ---- 生命周期 ----

    def create_task(self, inputs: TaskInputs, ssh_config: dict) -> Task:
        """创建任务(排队状态)并持久化"""
        with self._lock:
            task_id = uuid.uuid4().hex[:8]
            log_path = self.log_dir / f"{sanitize_task_name(inputs.resolved_name())}_{task_id}.log"
            task = Task(task_id, inputs, ssh_config, log_path)
            self.tasks[task_id] = task
        task.log_buffer.open()
        self.save_index()
        self._notify(task)
        return task

    def start_task(self, task_id: str) -> bool:
        """启动任务后台执行线程"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status != TaskStatus.QUEUED:
                return False
            task.cancel_flag.clear()
            runner = TaskRunner(task)
            task.thread = threading.Thread(
                target=runner.run, daemon=True,
                name=f"task-{task.name[:20]}")
            task.thread.start()
        return True

    def _set_status(self, task: Task, status: str):
        task.set_status(status, notify=lambda t: self._notify(t))
        self.save_index()

    def cancel_task(self, task_id: str) -> bool:
        """请求取消任务: 设置标记; 执行阶段同时停止容器以中断长测试"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status not in TaskStatus.ACTIVE:
                return False
            task.cancel_flag.set()
            task.log(tr("\n[取消] 收到取消请求, 正在终止任务...\n"))
            if task.status == TaskStatus.RUNNING and task.ssh and task.ssh.connected:
                try:
                    task.log(trf("[取消] 停止容器 {name} 以中断测试...\n",
                                 name=task.container_name))
                    task.ssh.execute(f"docker stop {task.container_name}")
                except Exception:
                    pass
        self._notify(task)
        return True

    def cleanup_task(self, task_id: str, ssh: SSHManager,
                     progress: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
        """清理任务远程资源(容器+临时目录), 需要可用的SSH连接"""
        def _log(text: str):
            if progress:
                progress(text)
            task.log(text)

        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False, tr("任务不存在")
            if task.status in TaskStatus.ACTIVE:
                return False, tr("任务仍在执行, 请先取消")
            if not ssh or not ssh.connected:
                return False, tr("SSH未连接, 无法清理远程资源")
            docker = DockerManager(ssh)

            if task.container_name:
                _log(trf("  停止并删除容器: {name}\n", name=task.container_name))
                docker.remove_container(task.container_name, callback=_log)
                task.container_name = ""
            if task.deploy_work_dir:
                docker.remote_work_base = task.deploy_work_dir
                if docker.work_dir_exists():
                    _log(trf("  清理临时部署目录: {dir}\n", dir=task.deploy_work_dir))
                    docker.remove_work_dir(callback=_log)
                task.deploy_work_dir = ""
            task.resources_cleaned = True
            self.save_index()
            self._notify(task)
            return True, tr("任务资源已清理")

    def copy_inputs(self, task_id: str) -> Optional[TaskInputs]:
        """复制任务的输入快照(用于预填创建任务表单)"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            return TaskInputs.from_dict(task.inputs.to_dict())

    def delete_task(self, task_id: str, delete_files: bool = False) -> bool:
        """删除任务记录; delete_files=True时同时删除本地日志与结果文件"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status in TaskStatus.ACTIVE:
                return False
            del self.tasks[task_id]
            task.log_buffer.close()
            self.save_index()
            if delete_files:
                self._delete_task_files(task)
        self._notify(task)
        return True

    @staticmethod
    def _delete_task_files(task: Task):
        """删除任务的本地数据文件(日志/结果目录/CSV)"""
        import shutil
        for path in (task.log_buffer.log_path, task.csv_path, task.result_dir):
            if not path:
                continue
            p = Path(path)
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                elif p.exists():
                    p.unlink()
            except OSError:
                pass

    def active_tasks(self) -> List[Task]:
        with self._lock:
            return [t for t in self.tasks.values() if t.status in TaskStatus.ACTIVE]

    def tasks_with_containers(self) -> List[Task]:
        """仍有远程容器资源未清理的任务"""
        with self._lock:
            return [t for t in self.tasks.values()
                    if t.container_name and not t.resources_cleaned]

    def get(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def shutdown(self):
        """关闭全部任务日志文件(程序退出时调用)"""
        with self._lock:
            for task in self.tasks.values():
                task.log_buffer.close()

    def all_tasks(self) -> List[Task]:
        """按创建时间倒序返回全部任务"""
        with self._lock:
            return sorted(self.tasks.values(),
                          key=lambda t: t.created_at, reverse=True)
