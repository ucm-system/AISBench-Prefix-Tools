import json
import base64
import unittest

import i18n
from docker_manager import DockerManager, describe_test_state


class FakeSSHManager:
    def __init__(self, output="", exit_code=0, error=""):
        self.output = output
        self.exit_code = exit_code
        self.error = error
        self.commands = []

    def execute(self, command, timeout=300):
        self.commands.append(command)
        return self.exit_code, self.output, self.error

    def file_exists(self, path):
        return True

    def mkdir_p(self, path):
        self.commands.append(f"mkdir -p {path}")

    def execute_with_callback(self, command, callback=None, timeout=300):
        self.commands.append(command)
        if callback:
            callback(self.output)
        return self.exit_code


class DockerManagerImageListTests(unittest.TestCase):
    def test_list_images_parses_named_images(self):
        payload = "\n".join([
            json.dumps({
                "Repository": "aisbench",
                "Tag": "v3.1",
                "ID": "abc123def456",
                "CreatedSince": "2 days ago",
                "Size": "12.3GB",
            }),
            json.dumps({
                "Repository": "<none>",
                "Tag": "<none>",
                "ID": "dangling",
                "CreatedSince": "1 day ago",
                "Size": "1.2GB",
            }),
        ])
        ssh = FakeSSHManager(payload)
        manager = DockerManager(ssh)

        images = manager.list_images()

        self.assertIn("docker image ls --format '{{json .}}'", ssh.commands[0])
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["name"], "aisbench:v3.1")
        self.assertEqual(images[0]["id"], "abc123def456")
        self.assertEqual(images[0]["created"], "2 days ago")
        self.assertEqual(images[0]["size"], "12.3GB")

    def test_list_images_reports_docker_failure(self):
        ssh = FakeSSHManager(error="Cannot connect to the Docker daemon", exit_code=1)
        manager = DockerManager(ssh)

        with self.assertRaisesRegex(RuntimeError, "Cannot connect"):
            manager.list_images()


class DockerManagerContainerTests(unittest.TestCase):
    def setUp(self):
        self.ssh = FakeSSHManager()
        self.manager = DockerManager(self.ssh)

    def test_create_container_mounts_model_only_and_adds_label(self):
        self.ssh.output = "Up 2 seconds"

        ok, name = self.manager.create_container(
            "aisbench:v3.1", "/mnt/models/ds", "aisbench-test-10101200"
        )

        self.assertTrue(ok)
        self.assertEqual(name, "aisbench-test-10101200")
        run_cmd = next(c for c in self.ssh.commands if c.startswith("docker run"))
        self.assertIn("--label org.aisbench-prefix-tools.managed=true", run_cmd)
        self.assertIn("-v /mnt/models/ds:/mnt/models/ds", run_cmd)
        self.assertNotIn("aisbench_auto_tools_prefix-main", run_cmd)
        self.assertEqual(self.manager.code_host_path, "")

    def test_list_managed_containers_filters_by_name_prefix_and_label(self):
        payload = "\n".join([
            json.dumps({
                "Names": "aisbench-test-09300120",
                "ID": "a1b2c3",
                "Image": "aisbench:v3.1",
                "Status": "Exited (0) 3 hours ago",
                "Labels": "",
                "RunningFor": "3 hours ago",
            }),
            json.dumps({
                "Names": "other-container",
                "ID": "d4e5f6",
                "Image": "ubuntu:24.04",
                "Status": "Up 2 hours",
                "Labels": "org.aisbench-prefix-tools.managed=true",
                "RunningFor": "2 hours ago",
            }),
            json.dumps({
                "Names": "nginx-proxy",
                "ID": "112233",
                "Image": "nginx",
                "Status": "Up 1 day",
                "Labels": "",
                "RunningFor": "1 day ago",
            }),
        ])
        self.ssh.output = payload

        containers = self.manager.list_managed_containers()

        self.assertEqual(len(containers), 2)
        self.assertEqual(containers[0]["name"], "aisbench-test-09300120")
        self.assertEqual(containers[1]["name"], "other-container")

    def test_write_file_in_container_uses_base64(self):
        self.manager.container_name = "aisbench-test-10101200"
        content = "MODEL_NAME = 'ds'\n"

        ok = self.manager.write_file_in_container(
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main/config.py", content
        )

        self.assertTrue(ok)
        cmd = self.ssh.commands[0]
        self.assertIn("docker exec aisbench-test-10101200 sh -c", cmd)
        payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
        self.assertIn(payload, cmd)
        self.assertIn("base64 -d", cmd)

    def test_read_file_in_container_decodes_base64(self):
        self.manager.container_name = "aisbench-test-10101200"
        content = "MODEL_NAME = 'ds'\n"
        self.ssh.output = base64.b64encode(content.encode("utf-8")).decode("ascii")

        result = self.manager.read_file_in_container("/tmp/config.py")

        self.assertEqual(result, content)

    def test_remove_work_dir_deletes_without_recreating(self):
        ok = self.manager.remove_work_dir()

        self.assertTrue(ok)
        self.assertIn("rm -rf /tmp/AISBench_Prefix_Tools", self.ssh.commands)
        self.assertNotIn("mkdir -p /tmp/AISBench_Prefix_Tools", self.ssh.commands)

    def test_copy_code_into_container_uses_docker_cp(self):
        self.manager.container_name = "aisbench-test-10101200"
        self.ssh.output = "run.py\nconfig.py\n"

        ok, target = self.manager.copy_code_into_container(
            "/tmp/AISBench_Prefix_Tools/aisbench_auto_tools_prefix-main"
        )

        self.assertTrue(ok)
        self.assertEqual(target, self.manager.code_mount_path)
        cp_cmd = next(
            c for c in self.ssh.commands if c.startswith("docker cp"))
        self.assertIn(
            "docker cp /tmp/AISBench_Prefix_Tools/aisbench_auto_tools_prefix-main/. "
            "aisbench-test-10101200:/benchmark/ais_bench/aisbench_auto_tools_prefix-main",
            cp_cmd,
        )

    def test_find_latest_log_dir_returns_container_path(self):
        self.manager.container_name = "aisbench-test-10101200"
        self.ssh.output = (
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main/test_logs_20261029_101112"
        )

        result = self.manager.find_latest_log_dir()

        self.assertEqual(
            result,
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main/test_logs_20261029_101112",
        )
        self.assertIn("docker exec aisbench-test-10101200 sh -c", self.ssh.commands[0])

    def test_write_script_writes_inside_container(self):
        self.manager.container_name = "aisbench-test-10101200"

        path = self.manager.write_script("echo hello", "run_tests.sh")

        self.assertEqual(path, f"{self.manager.code_mount_path}/run_tests.sh")
        self.assertIn("base64 -d", self.ssh.commands[0])
        self.assertTrue(any("chmod +x" in c for c in self.ssh.commands))

    def test_copy_code_into_container_writes_initialized_state(self):
        self.manager.container_name = "aisbench-test-10101200"
        self.ssh.output = "run.py\nconfig.py\n"

        ok, _ = self.manager.copy_code_into_container(
            "/tmp/AISBench_Prefix_Tools/aisbench_auto_tools_prefix-main"
        )

        self.assertTrue(ok)
        state_cmd = next(
            c for c in self.ssh.commands if ".aisbench_test_state" in c)
        self.assertIn("docker exec aisbench-test-10101200 sh -c", state_cmd)
        self.assertIn("initialized", state_cmd)

    def test_set_test_state_writes_marker_file(self):
        self.manager.container_name = "aisbench-test-10101200"
        logs = []

        ok = self.manager.set_test_state(
            DockerManager.TEST_STATE_RUNNING, callback=logs.append)

        self.assertTrue(ok)
        cmd = self.ssh.commands[0]
        self.assertIn("docker exec aisbench-test-10101200 sh -c", cmd)
        self.assertIn(".aisbench_test_state", cmd)
        self.assertIn("printf", cmd)
        self.assertIn("running > /benchmark/ais_bench/aisbench_auto_tools_prefix-main/.aisbench_test_state", cmd)
        self.assertEqual(logs, ["  ✓ 测试状态标记: 执行中\n"])

    def test_read_test_state_from_running_container(self):
        self.manager.container_name = "aisbench-test-10101200"
        self.ssh.output = "completed"

        state = self.manager.read_test_state()

        self.assertEqual(state, "completed")
        cmd = self.ssh.commands[0]
        self.assertIn("docker exec aisbench-test-10101200 sh -c", cmd)
        self.assertIn(".aisbench_test_state", cmd)

    def test_read_test_state_returns_none_for_unknown_value(self):
        self.manager.container_name = "aisbench-test-10101200"
        self.ssh.output = "not-a-state"

        self.assertIsNone(self.manager.read_test_state())

    def test_read_test_state_uses_docker_cp_for_stopped_container(self):
        class StoppedContainerSSH(FakeSSHManager):
            def execute(self, command, timeout=300):
                self.commands.append(command)
                if command.startswith("docker exec"):
                    return 1, "", "container is not running"
                if command.startswith("cat "):
                    return 0, "abnormal", ""
                return 0, "", ""

        ssh = StoppedContainerSSH()
        manager = DockerManager(ssh)

        state = manager.read_test_state("aisbench-test-09300120")

        self.assertEqual(state, "abnormal")
        self.assertTrue(any(c.startswith("docker cp aisbench-test-09300120:")
                            for c in ssh.commands))
        self.assertTrue(any(c.startswith("rm -f /tmp/aisbench_state_")
                            for c in ssh.commands))

    def test_read_test_state_returns_none_without_container(self):
        self.assertIsNone(self.manager.read_test_state())

    def test_list_managed_containers_includes_test_state(self):
        class RoutingSSH(FakeSSHManager):
            def __init__(self):
                super().__init__()
                self.ps_output = "\n".join([
                    json.dumps({
                        "Names": "aisbench-test-09300120",
                        "ID": "a1b2c3",
                        "Image": "aisbench:v3.1",
                        "Status": "Up 2 hours",
                        "Labels": "org.aisbench-prefix-tools.managed=true",
                        "RunningFor": "2 hours ago",
                    }),
                    json.dumps({
                        "Names": "aisbench-test-08300120",
                        "ID": "b2c3d4",
                        "Image": "aisbench:v3.1",
                        "Status": "Exited (0) 3 hours ago",
                        "Labels": "org.aisbench-prefix-tools.managed=true",
                        "RunningFor": "3 hours ago",
                    }),
                ])
                self.state_by_container = {
                    "aisbench-test-09300120": "running",
                    "aisbench-test-08300120": "running",
                }

            def execute(self, command, timeout=300):
                self.commands.append(command)
                if command.startswith("docker ps -a"):
                    return 0, self.ps_output, ""
                if command.startswith("docker exec"):
                    for name, state in self.state_by_container.items():
                        if name in command:
                            return 0, state, ""
                return 0, "", ""

        ssh = RoutingSSH()
        manager = DockerManager(ssh)

        containers = manager.list_managed_containers(include_test_state=True)

        by_name = {c["name"]: c for c in containers}
        self.assertEqual(by_name["aisbench-test-09300120"]["test_state"],
                         "running")
        self.assertEqual(by_name["aisbench-test-09300120"]["test_state_label"],
                         "执行中")
        # 容器已停止但状态标记停留在执行中 → 判定为上次会话中断
        self.assertEqual(by_name["aisbench-test-08300120"]["test_state"],
                         "running")
        self.assertEqual(by_name["aisbench-test-08300120"]["test_state_label"],
                         "异常终止(执行中断)")

    def test_describe_test_state_maps_all_states(self):
        i18n.set_language("zh")
        self.assertEqual(describe_test_state("initialized"), "初始化")
        self.assertEqual(describe_test_state("running"), "执行中")
        self.assertEqual(describe_test_state("completed"), "执行完成")
        self.assertEqual(describe_test_state("abnormal"), "异常终止")
        self.assertEqual(describe_test_state(None), "未标记")
        self.assertEqual(describe_test_state("running", False),
                         "异常终止(执行中断)")
        self.assertEqual(describe_test_state("running", True), "执行中")


class ConfigManagerContainerIOTests(unittest.TestCase):
    def test_config_is_written_and_read_inside_container(self):
        from config_manager import ConfigManager

        ssh = FakeSSHManager()
        docker = DockerManager(ssh)
        docker.container_name = "aisbench-test-10101200"
        manager = ConfigManager(docker)

        ok = manager.write_config_to_container({"model_name": "ds"})
        self.assertTrue(ok)
        write_cmd = ssh.commands[0]
        self.assertIn("docker exec aisbench-test-10101200 sh -c", write_cmd)
        self.assertIn("config.py", write_cmd)

        content = "MODEL_NAME = 'ds'\n"
        ssh.output = base64.b64encode(content.encode("utf-8")).decode("ascii")
        result = manager.read_config_from_container()
        self.assertEqual(result, content)


if __name__ == "__main__":
    unittest.main()
