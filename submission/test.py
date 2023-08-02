from copy import deepcopy
from unittest import mock
import hashlib
from options.options import SysOptions
from problem.models import Problem, ProblemTag
from utils.api.tests import APITestCase
from .models import Submission

DEFAULT_PROBLEM_DATA = {"_id": "A-110", "title": "test", "description": "<p>test</p>",
                        "visible": True, "tags": ["test"], "languages": ["C", "C++", "Java", "Python2"], "template": {},
                        "hint": "<p>test</p>", "lab_config": {"ttl":233, "packet_size":"32KB", "loss_rate": 0.05},
                        "vm_num": 2, "port_num": [1, 1], "code_num": 3}

DEFAULT_SUBMISSION_DATA = {
    "problem_id": "1",
    "user_id": 1,
    "username": "test",
    "server_list": ["113.232,12,23", "23.23.1.23"],
    "result": 4,
    "info": {},
    "code_list": ["iii", "iii", "iii"],
    "language": "C",
}

class SubmissionPrepare(APITestCase):
    def _create_problem(self):
        user = self.create_admin("test", "test123", login=False)
        problem_data = deepcopy(DEFAULT_PROBLEM_DATA)
        tags = problem_data.pop("tags")
        problem_data["created_by"] = user
        self.problem = Problem.objects.create(**problem_data)
        for tag in tags:
            tag = ProblemTag.objects.create(name=tag)
            self.problem.tags.add(tag)
        self.problem.save()

    def _create_problem_and_submission(self):
        user = self.create_admin("test", "test123", login=False)
        problem_data = deepcopy(DEFAULT_PROBLEM_DATA)
        tags = problem_data.pop("tags")
        problem_data["created_by"] = user
        self.problem = Problem.objects.create(**problem_data)
        for tag in tags:
            tag = ProblemTag.objects.create(name=tag)
            self.problem.tags.add(tag)
        self.problem.save()
        self.submission_data = deepcopy(DEFAULT_SUBMISSION_DATA)
        self.submission_data["problem_id"] = self.problem.id
        self.submission = Submission.objects.create(**self.submission_data)

class SubmissionListTest(SubmissionPrepare):
    def setUp(self):
        self._create_problem_and_submission()
        self.create_super_admin()
        self.url = self.reverse("submission_admin_api")

    def test_get_submission_list(self):
        resp = self.client.get(self.url, data={"limit": "10"})
        print(resp.data)
        self.assertSuccess(resp)


@mock.patch("submission.views.user.judge_task.send")
class SubmissionAPITest(SubmissionPrepare):
    def setUp(self):
        self._create_problem_and_submission()
        self.user = self.create_user("123", "test123")
        self.url = self.reverse("submission_api")

    def test_create_submission(self, judge_task):
        resp = self.client.post(self.url, self.submission_data)
        print(resp.data)
        self.assertSuccess(resp)
        judge_task.assert_called()

    def test_adjustStatus(self, judge_task):
        resp = self.client.post(self.url, self.submission_data)
        print(resp.data)
        self.assertSuccess(resp)
        judge_task.assert_called()
        self.url = self.reverse("submission_excution_api")
        self.data = {"hostname": "testhostname", "cpu_core": 4, "location": "Zhejiang",
                     "cpu_usage": 90.5, "memory_usage": 80.3, "action": "heartbeat", "service_url": "http://127.0.0.1",
                     "ready": False, "available_ports": [4000, 2000, 3233, 23232], "using_ports": [2000]}




class SubmissionDispathTest(SubmissionPrepare):
    def setUp(self):
        self._create_problem()
