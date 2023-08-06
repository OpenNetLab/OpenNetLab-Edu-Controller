import ipaddress
import hashlib
import requests
import logging
from django.db import transaction
from django.db.models import Q

from account.decorators import login_required, check_contest_permission
from account.models import User, UserProfile
from conf.models import JudgeServer
from contest.models import Contest, ContestStatus
from judge.testing import SubmissionTester
from options.options import SysOptions
from problem.models import Problem
from judge.tasks import local_judge_task
from judge.dispatcher import process_pending_task
from judge.dispatcher import JudgeStatus
from utils.api import APIView, validate_serializer, CSRFExemptAPIView
from utils.cache import cache
from utils.throttling import TokenBucket

from ..models import Submission
from ..serializers import (
    CreateSubmissionSerializer,
    SubmissionModelSerializer,
    ShareSubmissionSerializer,
)
from ..serializers import SubmissionSafeModelSerializer, SubmissionListSerializer

logger = logging.getLogger(__name__)

class SubmissionAPI(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = hashlib.sha256(
            SysOptions.judge_server_token.encode("utf-8")
        ).hexdigest()

    # redis queue buffering
    def throttling(self, request):
        auth_method = getattr(request, "auth_method", "")
        if auth_method == "api_key":
            return
        user_bucket = TokenBucket(
            key=str(request.user.id), redis_conn=cache, **SysOptions.throttling["user"]
        )
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

            if contest.allowed_ip_ranges:
                if not any(
                    user_ip in ipaddress.ip_network(cidr, strict=False)
                    for cidr in contest.allowed_ip_ranges
                ):
                    return self.error("Your IP is not allowed in this contest")

    # @validate_serializer(CreateSubmissionSerializer)
    @login_required
    def post(self, request):
        # print(request.data)
        data = request.data

        error = self.throttling(request)
        if error:
            return self.error(error)

        # get contset and check
        try:
            contest = Contest.objects.get(id=data["contest_id"])
            if contest.status == ContestStatus.CONTEST_ENDED:
                return self.error("The contest have ended")
            user_ip = ipaddress.ip_address(request.session.get("ip"))
            # ip check
            if contest.allowed_ip_ranges:
                if not any(
                    user_ip in ipaddress.ip_network(cidr, strict=False)
                    for cidr in contest.allowed_ip_ranges
                ):
                    return self.error("Your IP is not allowed in this contest")
        except Contest.DoesNotExist:
            return self.error("Contest not exist")

        # get problem and check
        try:
            problem = Problem.objects.get(
                id=data["problem_id"], contest_id=data.get("contest_id"), visible=True
            )
        except Problem.DoesNotExist:
            return self.error("Problem not exist")

        # check language
        if data["language"] not in problem.languages:
            return self.error(f"{data['language']} is now allowed in the problem")

        # check code list
        if len(data["code_list"]) != problem.code_num:
            return self.error("Code segment can't meet the requirement")

        submission = Submission.objects.create(
            user_id=request.user.id,
            contest=contest,
            problem=problem,
            username=request.user.username,
            result=JudgeStatus.PENDING,
            language=data["language"],
            code_list=data["code_list"],
            ip=request.session["ip"],
        )

        # execute judge task in dramatiq
        # local_judge_task.send(submission.id, problem._id)

        problem.submission_number += 1
        try:
            if SubmissionTester(submission).judge():
                problem.accepted_number += 1
        except Exception as e:
            self.error(str(e))
        problem.save()

        score = submission.grade
        user = User.objects.get(id=request.user.id)
        assert user
        profile = UserProfile.objects.get(user=user)
        assert profile
        if problem._id not in profile.problems_status:
            profile.problems_status[problem._id] = score
            profile.total_score += score
            if score == 100:
                profile.accepted_number += 1
        else:
            prev_score = profile.problems_status[problem._id]
            if score > prev_score:
                profile.problems_status[problem._id] = score
                profile.total_score += (score - prev_score)
                if score == 100:
                    profile.accepted_number += 1
        profile.save()

        return self.success(SubmissionModelSerializer(submission).data)

    @login_required
    def get(self, request):
        submission_id = request.GET.get("id")
        if not submission_id:
            submission_id = request.data.get("submission_id")
        if not submission_id:
            return self.error("Parameter id doesn't exist")
        try:
            submission = Submission.objects.select_related("problem").get(
                id=submission_id
            )
        except Submission.DoesNotExist:
            return self.error("Submission doesn't exist")
        if not submission.check_user_permission(request.user):
            return self.error("No permission for this submission")

        submission_data = SubmissionSafeModelSerializer(submission).data
        submission_data["can_unshare"] = submission.check_user_permission(
            request.user, check_share=False
        )
        submission_data["code_names"] = submission.problem.code_names
        return self.success(submission_data)

    @validate_serializer(ShareSubmissionSerializer)
    @login_required
    def put(self, request):
        """
        share submission
        """
        try:
            submission = Submission.objects.select_related("problem").get(
                id=request.data["id"]
            )
        except Submission.DoesNotExist:
            return self.error("Submission doesn't exist")
        if not submission.check_user_permission(request.user, check_share=False):
            return self.error("No permission to share the submission")
        if (
            submission.contest
            and submission.contest.status == ContestStatus.CONTEST_UNDERWAY
        ):
            return self.error("Can not share submission now")
        submission.shared = request.data["shared"]
        submission.save(update_fields=["shared"])
        return self.success()


class SubmissionListAPI(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = hashlib.sha256(
            SysOptions.judge_server_token.encode("utf-8")
        ).hexdigest()

    @login_required
    def get(self, request):
        if not request.GET.get("limit"):
            return self.error("Limit is needed")

        submissions = Submission.objects.filter(contest_id__isnull=True).filter(
            user_id=request.user.id
        )

        problem_id = request.GET.get("problem_id")
        result = request.GET.get("result")
        if problem_id:
            try:
                problem = Problem.objects.get(
                    _id=problem_id, contest_id__isnull=True, visible=True
                )
            except Problem.DoesNotExist:
                return self.error("Problem doesn't exist")
            submissions = submissions.filter(problem=problem)
        if result:
            submissions = submissions.filter(result=result)
        data = self.paginate_data(request, submissions)
        data["results"] = SubmissionListSerializer(
            data["results"], many=True, user=request.user
        ).data
        return self.success(data)


class ContestSubmissionListAPI(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token = hashlib.sha256(
            SysOptions.judge_server_token.encode("utf-8")
        ).hexdigest()

    def _request(self, url, data=None):
        kwargs = {"headers": {"X-Judge-Server-Token": self.token}}
        if data:
            kwargs["json"] = data
        try:
            return requests.post(url, **kwargs).json()
        except Exception as e:
            logger.exception(e)

    @check_contest_permission(check_type="submissions")
    def get(self, request):
        if not request.GET.get("limit"):
            return self.error("Limit is needed")
        if not request.GET.get("contest_id"):
            return self.error("Contest_id is needed")

        # first filter by contest
        contest_id = request.GET.get("contest_id")
        submissions = Submission.objects.filter(contest_id=contest_id)

        # filter by the request user id
        users = User.objects.filter(id=request.user.id)
        if len(users) == 0:
            self.error(f"no such user id: {request.user.id}")
        user = users[0]

        if not (user.is_admin_role() and int(request.GET.get('myself')) == 0):
            submissions = submissions.filter(user_id=request.user.id)

        if request.GET.get('username') != '':
            submissions = submissions.filter(username=request.GET.get('username'))

        # filter by problem names
        problem_name = request.GET.get("problem_name")
        if problem_name != "":
            problems = Problem.objects.filter(Q(_id__icontains=problem_name))
            submissions = submissions.filter(Q(problem__in=problems))
        
        data = self.paginate_data(request, submissions)
        data["results"] = SubmissionListSerializer(
            data["results"], many=True, user=request.user
        ).data

        # print(data)
        return self.success(data)


class SubmissionExistsAPI(APIView):
    def get(self, request):
        if not request.GET.get("problem_id"):
            return self.error("Parameter error, problem_id is required")
        return self.success(
            request.user.is_authenticated
            and Submission.objects.filter(
                problem_id=request.GET["problem_id"], user_id=request.user.id
            ).exists()
        )


class SubmissionUpdateAPI(CSRFExemptAPIView):
    @staticmethod
    def resource_fetch(submission: Submission) -> bool:
        vm_index = 0
        ports_list = submission.ports_list

        with transaction.atomic():
            for server_url in submission.server_list:
                try:
                    server = JudgeServer.objects.get(service_url=server_url)
                    server.available_ports = (
                        server.available_ports + ports_list[vm_index]
                    )
                    server.using_ports = list(
                        set(server.using_ports) - set(ports_list[vm_index])
                    )
                    server.available_ports_num = server.available_ports_num + len(
                        ports_list[vm_index]
                    )
                    server.save(
                        update_fields=[
                            "available_ports",
                            "using_ports",
                            "available_ports_num",
                        ]
                    )
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
            if (
                self.last_result != JudgeStatus.FINISHED
                and submission.result == JudgeStatus.FINISHED
            ):
                problem.accepted_number += 1
            problem.save(update_fields=["accepted_number"])
            user = User.objects.select_for_update().get(id=submission.user_id)
            user_profile = UserProfile.objects.get(user_id=user.id)
            problem_status = user_profile.problems_status.get("problems", {})
            if problem_id not in problem_status:
                problem_status[problem_id] = {
                    "status": submission.result,
                    "_id": problem.id,
                }
                if submission.result == JudgeStatus.FINISHED:
                    user_profile.accepted_number += 1
            elif problem_status[problem_id] != JudgeStatus.FINISHED:
                problem_status[problem_id]["status"] = submission.result
                if submission.result == JudgeStatus.FINISHED:
                    user_profile.accepted_number += 1
            user_profile.problems_status["problems"] = problem_status
            user_profile.save(update_fields=["accepted_number", "problems_status"])

    def update_contest_problem_status(self, submission: Submission):
        problem = submission.problem
        problem_id = str(problem.id)
        with transaction.atomic():
            # update contest problem status
            if (
                self.last_result != JudgeStatus.FINISHED
                and submission.result == JudgeStatus.FINISHED
            ):
                problem.accepted_number += 1
            problem.save(update_fields=["accepted_number"])
            user = User.objects.select_for_update().get(id=submission.user_id)
            user_profile = UserProfile.objects.get(user_id=user.id)
            contest_problems_status = user_profile.problems_status.get(
                "contest_problems", {}
            )
            if problem_id not in contest_problems_status:
                contest_problems_status[problem_id] = {
                    "status": submission.result,
                    "_id": problem._id,
                }
            elif contest_problems_status[problem_id]["status"] != JudgeStatus.ACCEPTED:
                contest_problems_status[problem_id]["status"] = submission.result
            else:
                # 已AC不计入
                return
            user_profile.problems_status["contest_problems"] = contest_problems_status
            user_profile.save(update_fields=["problems_status"])

    def post(self, request):
        data = request.data
        client_token = request.META.get("HTTP_X_JUDGE_SERVER_TOKEN")
        if (
            hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest()
            != client_token
        ):
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
        if result not in [
            JudgeStatus.PENDING,
            JudgeStatus.JUDGING,
        ] and self.last_result in [JudgeStatus.PENDING, JudgeStatus.JUDGING]:
            if not self.resource_fetch(submission):
                return self.error("resource Fetch error")
        submission.result = result
        submission.failed_info = data["info"]
        print("save result: ", result)
        submission.save(update_fields=["result", "info"])
        if submission.contest:
            self.update_contest_problem_status(submission)
        else:
            self.update_problem_status(submission)
        return self.success(SubmissionModelSerializer(submission).data)
