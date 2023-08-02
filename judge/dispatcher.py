import hashlib
import json
import logging
from urllib.parse import urljoin

import requests
from django.db import transaction, IntegrityError
from django.db.models import F

from account.models import User
from conf.models import JudgeServer
from contest.models import ContestStatus
from options.options import SysOptions
from problem.models import Problem
from problem.utils import parse_problem_template
from submission.models import JudgeStatus, Submission
from utils.cache import cache
from utils.constants import CacheKey

logger = logging.getLogger(__name__)


# 继续处理在队列中的问题
def process_pending_task():
    if cache.llen(CacheKey.waiting_queue):
        # 防止循环引入
        from judge.tasks import judge_task
        tmp_data = cache.rpop(CacheKey.waiting_queue)
        if tmp_data:
            data = json.loads(tmp_data.decode("utf-8"))
            judge_task.send(**data)


# 选择运行节点
class ChooseJudgeServer:
    def __init__(self, vm_num, ports):
        self.vm_num = vm_num
        self.ports = ports
        self.available_server = list()
        self.available_ports = list()

    def __enter__(self) -> [dict, None]:
        # 保持一致性
        print("Enter")
        with transaction.atomic():
            # 根据可用端口数量排序
            servers: list[JudgeServer] = JudgeServer.objects.select_for_update().order_by(
                "available_ports_num")
            servers = [s for s in servers if s.is_ready == True]
            print(servers)
            index = 0
            for server in servers:
                if server.task_number <= server.cpu_core * 8 and index < self.vm_num and self.ports[
                    index] < server.available_ports_num:
                    port_item = server.available_ports[0: self.ports[index]]
                    index = index + 1
                    self.available_server.append(server)
                    self.available_ports.append(port_item)
                    if index == self.vm_num:
                        break
            if index == self.vm_num:
                index = 0
                for server in self.available_server:
                    server.task_number = F("task_number") + 1
                    server.available_ports_num = F("available_ports_num") - self.ports[index]
                    server.available_ports = server.available_ports[self.ports[index]:]
                    server.using_ports = server.using_ports + self.available_ports[index]
                    server.save(update_fields=["task_number", "available_ports_num", "available_ports", "using_ports"])
                    index += 1
                return {"servers": self.available_server, "ports": self.available_ports}
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if len(self.available_server) == self.vm_num:
            for server in self.available_server:
                JudgeServer.objects.filter(id=server.id).update(task_number=F("task_number") - 1)


class DispatcherBase(object):
    def __init__(self):
        self.token = hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest()

    def _request(self, url, data=None):
        kwargs = {"headers": {"X-Judge-Server-Token": self.token}}
        if data:
            kwargs["json"] = data
        try:
            return requests.post(url, **kwargs).json()
        except Exception as e:
            logger.exception(e)


# 任务下发
class JudgeDispatcher(DispatcherBase):
    def __init__(self, submission_id, problem_id):
        super().__init__()
        self.submission = Submission.objects.get(id=submission_id)
        self.contest_id = self.submission.contest_id
        self.last_result = self.submission.result if self.submission.info else None
        if self.contest_id:
            self.problem = Problem.objects.select_related("contest").get(id=problem_id, contest_id=self.contest_id)
            self.contest = self.problem.contest
        else:
            self.problem = Problem.objects.get(id=problem_id)

    def resource_fetch(self):
        vm_index = 0
        submission = self.submission
        ports_list = submission.ports_list

        with transaction.atomic():
            for server_url in submission.server_list:
                try:
                    server = JudgeServer.objects.get(service_url=server_url)
                    server.available_ports = server.available_ports + ports_list[vm_index]
                    server.using_ports = list(set(server.using_ports) - set(ports_list[vm_index]))
                    server.available_ports_num = server.available_ports_num + len(ports_list[vm_index])
                    server.save(update_fields=["available_ports", "using_ports", "available_ports_num"])
                except JudgeServer.DoesNotExist:
                    return False
                vm_index += 1
        # 资源释放处理队列中的任务防止等待
        process_pending_task()
        return True

    def judge(self):
        language = self.submission.language
        code_list = self.submission.code_list

        data = {
            "submission_id": self.submission.id,
            "language_config": self.problem.languages,
            "lab_config": self.problem.lab_config,
            "src": code_list
        }

        # fix contest
        if self.problem.contest_id:
            data["lab_id"] = self.problem.lab_id
        else:
            data["lab_id"] = self.problem.id
        with ChooseJudgeServer(self.problem.vm_num, self.problem.port_num) as resources:
            # queue
            if not resources:
                data = {"submission_id": self.submission.id, "problem_id": self.problem.id}
                cache.lpush(CacheKey.waiting_queue, json.dumps(data))
                return
            servers: list[JudgeServer] = resources["servers"]
            ports: list[int] = resources["ports"]
            # load to submission
            self.submission.ports_list = ports
            data["ca_list"] = []
            data["c_cert_list"] = []
            data["c_key_list"] = []
            # Fix rejudge
            server_list = []
            for server in servers:
                server_list.append(server.service_url)
                data["ca_list"].append(server.ca_pem)
                data["c_cert_list"].append(server.c_cert)
                data["c_key_list"].append(server.c_key)
            self.submission.server_list = server_list
            self.submission.save(update_fields=["ports_list", "server_list"])
            Submission.objects.filter(id=self.submission.id).update(result=JudgeStatus.PENDING)
            data["ports"] = self.submission.ports_list
            data["server_list"] = self.submission.server_list
            vm_index = len(servers) - 1
            for server in reversed(servers):
                # change to a ONL_judgeProxy
                data["vm_index"] = vm_index

                resp = self._request(urljoin(server.service_url, "/judge"), data=data)

                if not resp:
                    self.resource_fetch()
                    Submission.objects.filter(id=self.submission.id).update(result=JudgeStatus.SYSTEM_ERROR)
                    return

                if resp["err"]:
                    Submission.objects.filter(id=self.submission.id).update(result=JudgeStatus.COMPILE_ERROR)
                    print(resp["data"])
                    self.submission.info["err_info"] = resp["data"]
                    self.submission.info["score"] = 0
                    # 回收资源
                    self.resource_fetch()
                    return
                vm_index -= 1

            Problem.objects.filter(id=self.problem.id).update(submission_number=F("submission_number") + 1)

        # 下发完成，尝试处理任务队列中剩余的任务
        process_pending_task()
