import ipaddress
import hashlib
from datetime import datetime

import requests
import logging
from urllib.parse import urljoin
from account.decorators import login_required, check_contest_permission
from contest.models import ContestStatus, ContestRuleType
from judge.tasks import judge_task
from options.options import SysOptions
from judge.dispatcher import JudgeDispatcher, process_pending_task
from problem.models import Problem
from judge.dispatcher import JudgeStatus
from utils.api import APIView, validate_serializer, CSRFExemptAPIView
from account.models import User, UserProfile
from django.db import transaction
from utils.cache import cache
from utils.throttling import TokenBucket
from judge.dispatcher import JudgeDispatcher
from conf.models import JudgeServer
from ..models import Submission
from ..serializers import (CreateSubmissionSerializer, SubmissionModelSerializer,
                           ShareSubmissionSerializer)
from ..serializers import SubmissionSafeModelSerializer, SubmissionListSerializer

logger = logging.getLogger(__name__)


class SubmissionAPI(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest()

    def _request(self, url, data=None):
        kwargs = {"headers": {"X-Judge-Server-Token": self.token}}
        if data:
            kwargs["json"] = data
        try:
            return requests.post(url, **kwargs).json()
        except Exception as e:
            logger.exception(e)

    def _rejudge(self, submission):
        submission.result = JudgeStatus.PENDING
        submission.info = ""
        judge_task.send(submission.id, submission.problem.id)

    def _update_status(self, submission):
        service_url = submission.server_list[0]
        data = {
            "submission_id": submission.id,
            "vm_index": 0
        }
        resp = self._request(urljoin(service_url, "/fetch"), data=data)
        if not resp or resp["err"]:
            return JudgeStatus.JUDGING
        elif resp["data"]["result"] == JudgeStatus.SYSTEM_ERROR and resp["data"]["info"] == "Need Rejudge":
            self._rejudge(submission)
        return resp["data"]["result"]

    # 存入Redis，作为一个队列缓冲
    def throttling(self, request):
        # 使用 open_api 的请求暂不做限制
        auth_method = getattr(request, "auth_method", "")
        if auth_method == "api_key":
            return
        user_bucket = TokenBucket(key=str(request.user.id),
                                  redis_conn=cache, **SysOptions.throttling["user"])
        can_consume, wait = user_bucket.consume()
        if not can_consume:
            return "Please wait %d seconds" % (int(wait))

        # ip_bucket = TokenBucket(key=request.session["ip"],
        #                         redis_conn=cache, **SysOptions.throttling["ip"])
        # can_consume, wait = ip_bucket.consume()
        # if not can_consume:
        #     return "Captcha is required"

    @check_contest_permission(check_type="problems")
    def check_contest_permission(self, request):
        contest = self.contest
        if contest.status == ContestStatus.CONTEST_ENDED:
            return self.error("The contest have ended")
        if not request.user.is_contest_admin(contest):
            user_ip = ipaddress.ip_address(request.session.get("ip"))

            # 如果设置了对子网的限制， 比如只能通过学校内网进行提交。
            if contest.allowed_ip_ranges:
                if not any(user_ip in ipaddress.ip_network(cidr, strict=False) for cidr in contest.allowed_ip_ranges):
                    return self.error("Your IP is not allowed in this contest")

    @validate_serializer(CreateSubmissionSerializer)
    @login_required
    def post(self, request):
        data = request.data
        hide_id = False
        if data.get("contest_id"):
            error = self.check_contest_permission(request)
            if error:
                return error
            contest = self.contest
            if not contest.problem_details_permission(request.user):
                hide_id = True

        error = self.throttling(request)
        if error:
            return self.error(error)

        try:
            problem = Problem.objects.get(id=data["problem_id"], contest_id=data.get("contest_id"), visible=True)
        except Problem.DoesNotExist:
            return self.error("Problem not exist")
        if data["language"] not in problem.languages:
            return self.error(f"{data['language']} is now allowed in the problem")
        if len(data["code_list"]) != problem.code_num:
            return self.error("Code segment can't meet the requirement")
        submission = Submission.objects.create(user_id=request.user.id,
                                               username=request.user.username,
                                               result=JudgeStatus.PENDING,
                                               language=data["language"],
                                               code_list=data["code_list"],
                                               problem_id=problem.id,
                                               ip=request.session["ip"],
                                               contest_id=data.get("contest_id"))

        # use this for debug
        # JudgeDispatcher(submission.id, problem.id).judge()
        judge_task.send(submission.id, problem.id)
        if hide_id:
            return self.success()
        else:
            return self.success(SubmissionModelSerializer(submission).data)

    @login_required
    def get(self, request):
        submission_id = request.GET.get("id")
        if not submission_id:
            submission_id = request.data.get("submission_id")
        if not submission_id:
            return self.error("Parameter id doesn't exist")
        try:
            submission = Submission.objects.select_related("problem").get(id=submission_id)
        except Submission.DoesNotExist:
            return self.error("Submission doesn't exist")
        if not submission.check_user_permission(request.user):
            return self.error("No permission for this submission")
        if submission.result in [JudgeStatus.JUDGING] or \
                (submission.result == [JudgeStatus.PENDING] and (
                        datetime.now() - submission.create_time).seconds) > 1800:
            submission.result = self._update_status(submission)
        submission_data = SubmissionSafeModelSerializer(submission).data
        # 是否有权限取消共享
        submission_data["can_unshare"] = submission.check_user_permission(request.user, check_share=False)
        return self.success(submission_data)

    # 代码共享，目前没啥用
    @validate_serializer(ShareSubmissionSerializer)
    @login_required
    def put(self, request):
        """
        share submission
        """
        try:
            submission = Submission.objects.select_related("problem").get(id=request.data["id"])
        except Submission.DoesNotExist:
            return self.error("Submission doesn't exist")
        if not submission.check_user_permission(request.user, check_share=False):
            return self.error("No permission to share the submission")
        if submission.contest and submission.contest.status == ContestStatus.CONTEST_UNDERWAY:
            return self.error("Can not share submission now")
        submission.shared = request.data["shared"]
        submission.save(update_fields=["shared"])
        return self.success()


# 基本实验类型, 系统设计者给出, 每个人只能看到自己的提交记录
class SubmissionListAPI(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest()

    def _rejudge(self, submission):
        submission.result = JudgeStatus.PENDING
        submission.info = None
        submission.result = JudgeStatus.PENDING
        submission.save(update_fields=["result", "info"])
        judge_task.send(submission.id, submission.problem.id)

    def _request(self, url, data=None):
        kwargs = {"headers": {"X-Judge-Server-Token": self.token}}
        if data:
            kwargs["json"] = data
        try:
            return requests.post(url, **kwargs).json()
        except Exception as e:
            logger.exception(e)

    def _update_status(self, submission):
        service_url = submission.server_list[0]
        data = {
            "submission_id": submission.id,
            "vm_index": 0
        }
        resp = self._request(urljoin(service_url, "/fetch"), data=data)
        print(resp)
        if not resp or resp["err"]:
            return JudgeStatus.JUDGING
        elif resp["data"]["result"] == JudgeStatus.SYSTEM_ERROR and resp["data"]["info"] == "Need Rejudge":
            self._rejudge(submission)
            return JudgeStatus.PENDING
        return resp["data"]["result"]

    @login_required
    def get(self, request):
        if not request.GET.get("limit"):
            return self.error("Limit is needed")

        submissions = Submission.objects.filter(contest_id__isnull=True).filter(user_id=request.user.id)

        for submission in submissions:

            if submission.result in [JudgeStatus.JUDGING] or \
                    (submission.result == [JudgeStatus.PENDING] and (datetime.now() - submission.create_time).seconds) > 1800:
                submission.result = self._update_status(submission)

        problem_id = request.GET.get("problem_id")
        result = request.GET.get("result")
        if problem_id:
            try:
                problem = Problem.objects.get(_id=problem_id, contest_id__isnull=True, visible=True)
            except Problem.DoesNotExist:
                return self.error("Problem doesn't exist")
            submissions = submissions.filter(problem=problem)
        if result:
            submissions = submissions.filter(result=result)
        data = self.paginate_data(request, submissions)
        data["results"] = SubmissionListSerializer(data["results"], many=True, user=request.user).data
        return self.success(data)


class ContestSubmissionListAPI(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest()

    def _rejudge(self, submission):
        submission.result = JudgeStatus.PENDING
        submission.info = None
        submission.result = JudgeStatus.PENDING
        submission.save(update_fields=["result", "info"])
        judge_task.send(submission.id, submission.problem.id)

    def _request(self, url, data=None):
        kwargs = {"headers": {"X-Judge-Server-Token": self.token}}
        if data:
            kwargs["json"] = data
        try:
            return requests.post(url, **kwargs).json()
        except Exception as e:
            logger.exception(e)

    def _update_status(self, submission):
        service_url = submission.server_list[0]
        data = {
            "submission_id": submission.id,
            "vm_index": 0
        }
        resp = self._request(urljoin(service_url, "/fetch"), data=data)
        print(resp)
        if not resp or resp["err"]:
            return JudgeStatus.JUDGING
        elif resp["data"]["result"] == JudgeStatus.SYSTEM_ERROR and resp["data"]["info"] == "Need Rejudge":
            self._rejudge(submission)
            return JudgeStatus.PENDING
        return resp["data"]["result"]

    @check_contest_permission(check_type="submissions")
    def get(self, request):
        if not request.GET.get("limit"):
            return self.error("Limit is needed")
        if not request.GET.get("contest_id"):
            return self.error("Contest_id is needed")

        contest_id = request.GET.get("contest_id")
        submissions = Submission.objects.filter(contest_id=contest_id).filter(user_id=request.user.id)
        for submission in submissions:
            if submission.result in [JudgeStatus.JUDGING] or \
                    (submission.result == [JudgeStatus.PENDING] and (
                            datetime.now() - submission.create_time).seconds) > 1800:
                submission.result = self._update_status(submission)

        problem_id = request.GET.get("problem_id")
        result = request.GET.get("result")
        if problem_id:
            try:
                problem = Problem.objects.get(_id=problem_id, contest_id=contest_id, visible=True)
            except Problem.DoesNotExist:
                return self.error("Problem doesn't exist")
            submissions = submissions.filter(problem=problem)

        if result:
            submissions = submissions.filter(result=result)

        # filter the test submissions submitted before contest start

        data = self.paginate_data(request, submissions)
        data["results"] = SubmissionListSerializer(data["results"], many=True, user=request.user).data
        return self.success(data)


class SubmissionExistsAPI(APIView):
    def get(self, request):
        if not request.GET.get("problem_id"):
            return self.error("Parameter error, problem_id is required")
        return self.success(request.user.is_authenticated and
                            Submission.objects.filter(problem_id=request.GET["problem_id"],
                                                      user_id=request.user.id).exists())


class SubmissionUpdateAPI(CSRFExemptAPIView):
    @staticmethod
    def resource_fetch(submission: Submission) -> bool:
        vm_index = 0
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

    def update_problem_status(self, submission: Submission):
        problem = submission.problem
        problem_id = str(problem.id)
        with transaction.atomic():
            # update problem status
            if self.last_result != JudgeStatus.ACCEPTED and submission.result == JudgeStatus.ACCEPTED:
                problem.accepted_number += 1
            problem.save(update_fields=["accepted_number"])
            user = User.objects.select_for_update().get(id=submission.user_id)
            user_profile = UserProfile.objects.get(user_id=user.id)
            problem_status = user_profile.problems_status.get("problems", {})
            if problem_id not in problem_status:
                problem_status[problem_id] = {"status": submission.result, "_id": problem.id}
                if submission.result == JudgeStatus.ACCEPTED:
                    user_profile.accepted_number += 1
            elif problem_status[problem_id] != JudgeStatus.ACCEPTED:
                problem_status[problem_id]["status"] = submission.result
                if submission.result == JudgeStatus.ACCEPTED:
                    user_profile.accepted_number += 1
            user_profile.problems_status["problems"] = problem_status
            user_profile.save(update_fields=["accepted_number", "problems_status"])

    def update_contest_problem_status(self, submission: Submission):
        problem = submission.problem
        problem_id = str(problem.id)
        with transaction.atomic():
            # update contest problem status
            if self.last_result != JudgeStatus.ACCEPTED and submission.result == JudgeStatus.ACCEPTED:
                problem.accepted_number += 1
            problem.save(update_fields=["accepted_number"])
            user = User.objects.select_for_update().get(id=submission.user_id)
            user_profile = UserProfile.objects.get(user_id=user.id)
            contest_problems_status = user_profile.problems_status.get("contest_problems", {})
            if problem_id not in contest_problems_status:
                contest_problems_status[problem_id] = {"status": submission.result, "_id": problem._id}
            elif contest_problems_status[problem_id]["status"] != JudgeStatus.ACCEPTED:
                contest_problems_status[problem_id]["status"] = submission.result
            else:
                # 已AC不计入
                return
            user_profile.problems_status["contest_problems"] = contest_problems_status
            user_profile.save(update_fields=["problems_status"])

    def post(self, request):
        data = request.data
        print(data)
        client_token = request.META.get("HTTP_X_JUDGE_SERVER_TOKEN")
        if hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest() != client_token:
            return self.error("Invalid token")
        try:
            server = JudgeServer.objects.get(ip=request.ip)
        except JudgeServer.DoesNotExist:
            return self.error("illegal server submission put")
        if "submission_id" not in data:
            return self.error("submission_id is needed")
        submission_id = data.pop("submission_id")
        try:
            submission = Submission.objects.get(id=submission_id)
        except Submission.DoesNotExist:
            return self.error("submmission not exist or expired")
        if "result" not in data:
            return self.error("submission result is needed")
        self.last_result = submission.result
        result = data["result"]
        if result not in [JudgeStatus.PENDING, JudgeStatus.JUDGING] and self.last_result in [JudgeStatus.PENDING, JudgeStatus.JUDGING]:
            if not self.resource_fetch(submission):
                return self.error("resource Fetch error")
        submission.result = result
        submission.info = data["info"]
        print("save result: ", result)
        submission.save(update_fields=["result", "info"])
        if submission.contest:
            self.update_contest_problem_status(submission)
        else:
            self.update_problem_status(submission)
        return self.success(SubmissionModelSerializer(submission).data)