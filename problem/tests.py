import copy
import hashlib
import os
import shutil
from datetime import timedelta
from zipfile import ZipFile

from django.conf import settings

from utils.api.tests import APITestCase
from .serializers import ProblemAdminSerializer
from .models import ProblemTag
from .models import Problem
from contest.models import Contest
from contest.tests import DEFAULT_CONTEST_DATA

from .utils import parse_problem_template

DEFAULT_PROBLEM_DATA = {"_id": "A-110", "title": "test", "description": "<p>test</p>",
                        "visible": True, "tags": ["test"], "languages": ["C", "C++", "Java", "Python2"], "template": {},
                        "hint": "<p>test</p>", "lab_config": {"ttl":233, "packet_size":"32KB", "loss_rate": 0.05},
                        "vm_num": 2, "port_num": [1, 1], "code_num": 3, "share_submission": True}


class ProblemCreateTestBase(APITestCase):
    @staticmethod
    def add_problem(problem_data, created_by):
        data = copy.deepcopy(problem_data)
        total_score = 0
        data["total_score"] = total_score
        data["created_by"] = created_by
        tags = data.pop("tags")
        data["languages"] = list(data["languages"])
        problem = Problem.objects.create(**data)
        for item in tags:
            try:
                tag = ProblemTag.objects.get(name=item)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=item)
            problem.tags.add(tag)
        return problem


class ProblemTagListAPITest(APITestCase):
    def test_get_tag_list(self):
        ProblemTag.objects.create(name="name1")
        ProblemTag.objects.create(name="name2")
        resp = self.client.get(self.reverse("problem_tag_list_api"))
        self.assertSuccess(resp)



class ProblemAdminAPITest(APITestCase):
    def setUp(self):
        self.url = self.reverse("problem_admin_api")
        self.create_super_admin()
        self.data = copy.deepcopy(DEFAULT_PROBLEM_DATA)

    def test_create_problem(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        return resp

    def test_duplicate_display_id(self):
        self.test_create_problem()

        resp = self.client.post(self.url, data=self.data)
        self.assertFailed(resp, "Display ID already exists")

    def test_get_problem(self):
        self.test_create_problem()
        resp = self.client.get(self.url)
        print(resp.data)
        self.assertSuccess(resp)

    def test_get_one_problem(self):
        problem_id = self.test_create_problem().data["data"]["id"]
        resp = self.client.get(self.url + "?id=" + str(problem_id))
        self.assertSuccess(resp)

    def test_edit_problem(self):
        problem_id = self.test_create_problem().data["data"]["id"]
        data = copy.deepcopy(self.data)
        data["id"] = problem_id
        data["vm_num"] = 3
        # resp = self.client.put(self.url, data=data)
        resp = self.client.get(self.url, data)
        print("vm_num:", resp.data)
        self.assertSuccess(resp)


class ProblemAPITest(ProblemCreateTestBase):
    def setUp(self):
        self.url = self.reverse("problem_api")
        admin = self.create_admin(login=False)
        self.problem = self.add_problem(DEFAULT_PROBLEM_DATA, admin)
        self.create_user("test", "test123")

    def test_get_problem_list(self):
        resp = self.client.get(f"{self.url}?limit=10")
        print(resp.data)
        self.assertSuccess(resp)

    def test_get_one_problem(self):
        resp = self.client.get(self.url + "?problem_id=" + self.problem._id)
        print(resp.data)
        self.assertSuccess(resp)


class ContestProblemAdminTest(ProblemCreateTestBase):
    def setUp(self):
        self.url = self.reverse("contest_problem_admin_api")
        self.user = self.create_admin()
        self.problem = self.add_problem(DEFAULT_PROBLEM_DATA, self.user)
        self.contest = self.client.post(self.reverse("contest_admin_api"), data=DEFAULT_CONTEST_DATA).data["data"]
        self.data = {
            "display_id": "1000",
            "contest_id": self.contest["id"],
            "problem_id": self.problem.id,
            "lab_config": {"loss_rate": 0.1, "packet_size": "32MB"}
        }

    def test_create_contest_problem(self):
        resp = self.client.post(self.url, data=self.data)
        self.assertSuccess(resp)
        return resp.data["data"]

    def test_get_contest_problem(self):
        self.test_create_contest_problem()
        self.data["display_id"]="2000"
        self.client.post(self.url, data=self.data)
        contest_id = self.contest["id"]
        resp = self.client.get(self.url + "?contest_id=" + str(contest_id))
        print(resp.data)
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]["results"]), 2)

    def test_get_one_contest_problem(self):
        contest_problem = self.test_create_contest_problem()
        contest_id = self.contest["id"]
        problem_id = contest_problem["id"]
        resp = self.client.get(f"{self.url}?contest_id={contest_id}&id={problem_id}")
        self.assertSuccess(resp)


class ContestProblemTest(ProblemCreateTestBase):
    def setUp(self):
        admin = self.create_admin()
        url = self.reverse("contest_admin_api")
        contest_data = copy.deepcopy(DEFAULT_CONTEST_DATA)
        contest_data["password"] = ""
        contest_data["start_time"] = contest_data["start_time"] + timedelta(hours=1)
        self.contest = self.client.post(url, data=contest_data).data["data"]
        self.problem = self.add_problem(DEFAULT_PROBLEM_DATA, admin)
        self.problem.contest_id = self.contest["id"]
        self.problem.save()
        self.url = self.reverse("contest_problem_api")

    def test_admin_get_contest_problem_list(self):
        contest_id = self.contest["id"]
        resp = self.client.get(self.url + "?contest_id=" + str(contest_id))
        self.assertSuccess(resp)
        self.assertEqual(len(resp.data["data"]), 1)

    def test_admin_get_one_contest_problem(self):
        contest_id = self.contest["id"]
        problem_id = self.problem._id
        resp = self.client.get("{}?contest_id={}&problem_id={}".format(self.url, contest_id, problem_id))
        print(resp.data)
        self.assertSuccess(resp)

    def test_regular_user_get_not_started_contest_problem(self):
        self.create_user("test", "test123")
        resp = self.client.get(self.url + "?contest_id=" + str(self.contest["id"]))
        contest = Contest.objects.get(id=self.contest["id"])
        print(contest.status)
        print(resp.data)
        self.assertDictEqual(resp.data, {"error": "error", "data": "Contest has not started yet."})

    def test_reguar_user_get_started_contest_problem(self):
        self.create_user("test", "test123")
        contest = Contest.objects.first()
        contest.start_time = contest.start_time - timedelta(hours=1)
        contest.save()
        resp = self.client.get(self.url + "?contest_id=" + str(self.contest["id"]))
        print(resp.data)
        self.assertSuccess(resp)


class AddProblemFromPublicProblemAPITest(ProblemCreateTestBase):
    def setUp(self):
        admin = self.create_admin()
        url = self.reverse("contest_admin_api")
        contest_data = copy.deepcopy(DEFAULT_CONTEST_DATA)
        contest_data["password"] = ""
        contest_data["start_time"] = contest_data["start_time"] + timedelta(hours=1)
        self.contest = self.client.post(url, data=contest_data).data["data"]
        self.problem = self.add_problem(DEFAULT_PROBLEM_DATA, admin)
        self.url = self.reverse("add_contest_problem_from_public_api")
        self.data = {
            "display_id": "1000",
            "contest_id": self.contest["id"],
            "problem_id": self.problem.id,
            "lab_config": {"loss_rate": 0.1, "packet_size": "32MB"}
        }

    def test_add_contest_problem(self):
        resp = self.client.post(self.url, data=self.data)
        for problem in Problem.objects.all():
            print(ProblemAdminSerializer(problem).data)
        self.assertSuccess(resp)
        self.assertTrue(Problem.objects.all().exists())
        self.assertTrue(Problem.objects.filter(contest_id=self.contest["id"]).exists())


class ParseProblemTemplateTest(APITestCase):
    def test_parse(self):
        template_str = """
//PREPEND BEGIN
aaa
//PREPEND END

//TEMPLATE BEGIN
bbb
//TEMPLATE END

//APPEND BEGIN
ccc
//APPEND END
"""

        ret = parse_problem_template(template_str)
        self.assertEqual(ret["prepend"], "aaa\n")
        self.assertEqual(ret["template"], "bbb\n")
        self.assertEqual(ret["append"], "ccc\n")

    def test_parse1(self):
        template_str = """
//PREPEND BEGIN
aaa
//PREPEND END

//APPEND BEGIN
ccc
//APPEND END
//APPEND BEGIN
ddd
//APPEND END
"""

        ret = parse_problem_template(template_str)
        self.assertEqual(ret["prepend"], "aaa\n")
        self.assertEqual(ret["template"], "")
        self.assertEqual(ret["append"], "ccc\n")
