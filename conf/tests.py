import hashlib
from copy import deepcopy
from unittest import mock

from problem.models import Problem, ProblemTag
from submission.models import Submission
from submission.serializers import SubmissionModelSerializer
from django.conf import settings
from django.utils import timezone
from judge.dispatcher import JudgeDispatcher
from conf.serializers import JudgeServerSerializer
from options.options import SysOptions
from utils.api.tests import APITestCase
from .models import JudgeServer

DEFAULT_PROBLEM_DATA = {"_id": "A-110", "title": "test", "description": "<p>test</p>",
                        "visible": True, "tags": ["test"], "languages": ["C", "C++", "Java", "Python2"], "template": {},
                        "hint": "<p>test</p>", "lab_config": {"ttl":233, "packet_size":"32KB", "loss_rate": 0.05},
                        "vm_num": 1, "port_num": [2], "code_num": 3}

DEFAULT_SUBMISSION_DATA = {
    "problem_id": "1",
    "user_id": 1,
    "username": "test",
    "server_list": ["113.232,12,23", "23.23.1.23"],
    "result": -2,
    "info": {},
    "code_list": ["iii", "iii", "iii"],
    "language": "C",
}


class SMTPConfigTest(APITestCase):
    def setUp(self):
        self.user = self.create_super_admin()
        self.url = self.reverse("smtp_admin_api")
        self.password = "testtest"

    def test_create_smtp_config(self):
        data = {"server": "smtp.test.com", "email": "test@test.com", "port": 465,
                "tls": True, "password": self.password}
        resp = self.client.post(self.url, data=data)
        self.assertSuccess(resp)
        self.assertTrue("password" not in resp.data)
        return resp

    def test_edit_without_password(self):
        self.test_create_smtp_config()
        data = {"server": "smtp1.test.com", "email": "test2@test.com", "port": 465,
                "tls": True}
        resp = self.client.put(self.url, data=data)
        self.assertSuccess(resp)

    def test_edit_without_password1(self):
        self.test_create_smtp_config()
        data = {"server": "smtp.test.com", "email": "test@test.com", "port": 465,
                "tls": True, "password": ""}
        resp = self.client.put(self.url, data=data)
        self.assertSuccess(resp)

    def test_edit_with_password(self):
        self.test_create_smtp_config()
        data = {"server": "smtp1.test.com", "email": "test2@test.com", "port": 465,
                "tls": True, "password": "newpassword"}
        resp = self.client.put(self.url, data=data)
        self.assertSuccess(resp)

    @mock.patch("conf.views.send_email")
    def test_test_smtp(self, mocked_send_email):
        url = self.reverse("smtp_test_api")
        self.test_create_smtp_config()
        resp = self.client.post(url, data={"email": "test@test.com"})
        self.assertSuccess(resp)
        mocked_send_email.assert_called_once()


class WebsiteConfigAPITest(APITestCase):
    def test_create_website_config(self):
        self.create_super_admin()
        url = self.reverse("website_config_api")
        data = {"website_base_url": "http://test.com", "website_name": "test name",
                "website_name_shortcut": "test oj", "website_footer": "<a>test</a>",
                "allow_register": True, "submission_list_show_all": False}
        resp = self.client.post(url, data=data)
        self.assertSuccess(resp)

    def test_edit_website_config(self):
        self.create_super_admin()
        url = self.reverse("website_config_api")
        data = {"website_base_url": "http://test.com", "website_name": "test name",
                "website_name_shortcut": "test oj", "website_footer": "<img onerror=alert(1) src=#>",
                "allow_register": True, "submission_list_show_all": False}
        resp = self.client.post(url, data=data)
        self.assertSuccess(resp)
        self.assertEqual(SysOptions.website_footer, '<img src="#" />')

    def test_get_website_config(self):
        # do not need to login
        url = self.reverse("website_info_api")
        resp = self.client.get(url)
        self.assertSuccess(resp)

#测试heart
class JudgeServerHeartbeatTest(APITestCase):
    def setUp(self):
        self.url = self.reverse("judge_server_heartbeat_api")

        self.data = {"hostname": "testhostname", "cpu_core": 4, "location": "Zhejiang",
                     "cpu_usage": 90.5, "memory_usage": 80.3, "service_url": "http://127.0.0.1",
                     "ready": False, "available_ports": [4000, 2000, 3233, 23232], "using_ports": [2000]}
        self.token = "test"
        self.hashed_token = hashlib.sha256(self.token.encode("utf-8")).hexdigest()
        SysOptions.judge_server_token = self.token
        self.headers = {"HTTP_X_JUDGE_SERVER_TOKEN": self.hashed_token, settings.IP_HEADER: "1.2.3.4"}

    def test_new_heartbeat(self):
        resp = self.client.post(self.url, data=self.data, **self.headers)
        self.assertSuccess(resp)
        server = JudgeServer.objects.first()
        # print(self.data)
        # print(server.available_ports)
        # print(server.using_ports)
        # print(server.available_ports_num)
        # print(server.is_ready)
        self.assertEqual(server.ip, "127.0.0.1")


    def test_update_heartbeat(self):
        self.test_new_heartbeat()
        data = self.data
        data["using_ports"] = []
        data["is_ready"] = True
        resp = self.client.post(self.url, data=data, **self.headers)
        server = JudgeServer.objects.first()
        # print(server.available_ports)
        # print(server.using_ports)
        # print(server.available_ports_num)
        # print(server.is_ready)
        # print(resp.data)
        self.assertSuccess(resp)
        self.assertEqual(JudgeServer.objects.get(hostname=self.data["hostname"]).available_ports_num, len(data["available_ports"]) - len(data["using_ports"]))

    def test_judge(self):
        self.test_update_heartbeat()
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
        self.user = self.create_user("123", "test123")
        self.url = self.reverse("submission_api")
        resp = self.client.post(self.url, self.submission_data)
        self.assertSuccess(resp)
        servers = JudgeServer.objects.all()
        print(servers)
        JudgeDispatcher(resp.data["data"]["id"], self.problem.id).judge()
        submission = Submission.objects.get(id=resp.data["data"]["id"])
        server: JudgeServer = JudgeServer.objects.first()
        print(JudgeServerSerializer(server).data)
        print(SubmissionModelSerializer(submission).data)

class JudgeServerAPITest(APITestCase):
    def setUp(self):
        self.server = JudgeServer.objects.create(**{"hostname": "testhostname", "cpu_core": 4, "location": "Zhejiang",
                     "cpu_usage": 90.5, "memory_usage": 80.3, "service_url": "http://127.0.0.1",
                     "is_ready": False, "available_ports": [4000, 2000, 3233, 23232], "using_ports": [2000], "last_heartbeat": timezone.now()})
        self.url = self.reverse("judge_server_api")
        self.create_super_admin()

    def test_get_judge_server(self):
        resp = self.client.get(self.url)
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]["servers"]), 1)

    def test_delete_judge_server(self):
        resp = self.client.delete(self.url + "?hostname=testhostname")
        self.assertSuccess(resp)
        self.assertFalse(JudgeServer.objects.filter(hostname="testhostname").exists())

    def test_disabled_judge_server(self):
        resp = self.client.put(self.url, data={"is_disabled": True, "id": self.server.id})
        self.assertSuccess(resp)
        self.assertTrue(JudgeServer.objects.get(id=self.server.id).is_disabled)


class LanguageListAPITest(APITestCase):
    def test_get_languages(self):
        resp = self.client.get(self.reverse("language_list_api"))
        self.assertSuccess(resp)


class TestCasePruneAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("prune_test_case_api")
        self.create_super_admin()

    def test_get_isolated_test_case(self):
        resp = self.client.get(self.url)
        self.assertSuccess(resp)

    @mock.patch("conf.views.TestCasePruneAPI.delete_one")
    @mock.patch("conf.views.os.listdir")
    @mock.patch("conf.views.Problem")
    def test_delete_test_case(self, mocked_problem, mocked_listdir, mocked_delete_one):
        valid_id = "1172980672983b2b49820be3a741b109"
        mocked_problem.return_value = [valid_id, ]
        mocked_listdir.return_value = [valid_id, ".test", "aaa"]
        resp = self.client.delete(self.url)
        self.assertSuccess(resp)
        mocked_delete_one.assert_called_once_with(valid_id)


class ReleaseNoteAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("get_release_notes_api")
        self.create_super_admin()
        self.latest_data = {"update": [
            {
                "version": "2099-12-25",
                "level": 1,
                "title": "Update at 2099-12-25",
                "details": ["test get", ]
            }
        ]}

    def test_get_versions(self):
        resp = self.client.get(self.url)
        self.assertSuccess(resp)


class DashboardInfoAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("dashboard_info_api")
        self.create_admin()

    def test_get_info(self):
        resp = self.client.get(self.url)
        self.assertSuccess(resp)
        self.assertEqual(resp.data["data"]["user_count"], 1)
