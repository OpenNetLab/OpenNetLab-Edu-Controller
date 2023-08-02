import hashlib
from account.decorators import super_admin_required, admin_role_required, ensure_created_by, ensure_managed_by
from judge.tasks import judge_task
# from judge.dispatcher import JudgeDispatcher
from utils.api import APIView
from ..serializers import SubmissionModelSerializer
from ..models import Submission, JudgeStatus
import logging
import requests
from urllib.parse import urljoin
from contest.models import Contest
from problem.models import Problem
from conf.models import JudgeServer
from account.models import User, UserProfile
from options.options import SysOptions

logger = logging.getLogger(__name__)


class SubmissionRejudgeAPI(APIView):
    @super_admin_required
    def get(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Parameter error, id is required")
        try:
            submission = Submission.objects.select_related("problem").get(id=id, contest_id__isnull=True)
        except Submission.DoesNotExist:
            return self.error("Submission does not exists")
        submission.statistic_info = {}
        submission.save()

        judge_task.send(submission.id, submission.problem.id)
        return self.success()


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

    def _update_status(self, submission):
        service_url = submission.server_list[0]
        data = {
            "submission_id": submission.id,
            "vm_index": 0
        }
        if submission.problem.lab_id:
            data["lab_id"] = submission.problem.lab_id
        else:
            data["lab_id"] = submission.problem.id
        resp = self._request(urljoin(service_url, "/fetch"), data=data)
        if not resp or resp["err"]:
            return JudgeStatus.JUDGING
        else:
            return resp.data["result"]

    @admin_role_required
    def get(self, request):
        user = request.user
        submission_id = request.GET.get("id")
        if submission_id:
            try:
                submission = Submission.objects.get(id=submission_id)
                if submission.problem.contest:
                    ensure_managed_by(submission.problem.contest, user.id)
                else:
                    ensure_created_by(submission.problem, user)
                # 主动查询
                if submission.result in [JudgeStatus.JUDGING]:
                    result = self._update_status(submission)
                    submission.result = result
                return self.success(SubmissionModelSerializer(submission).data)
            except Submission.DoesNotExist:
                return self.error("Submission not exist")

        find_user_id = request.GET.get("find_user_id")
        problem_id = request.GET.get("problem_id")
        contest_id = request.GET.get("contest_id")
        if user.is_super_admin():
            submissions = Submission.objects.all()
        else:
            submissions = Submission.objects.filter(contest__contest_admin__in=user.id)
        if contest_id:
            try:
                contest = Contest.objects.get(id=contest_id)
            except Contest.DoesNotExist:
                return self.error("Contest not exist")
            submissions.filter(contest=contest)
        if problem_id:
            try:
                problem = Problem.objects.get(id=problem_id)
            except Problem.DoesNotExist:
                return self.error("Problem not exist")
            submissions.filter(problem=problem)
        if find_user_id:
            try:
                user = User.objects.get(userid=find_user_id)
            except User.DoesNotExist:
                return self.error("User not exist")
            submissions.filter(user_id=find_user_id)
        # 主动查询
        for submission in submissions:
            if submission.result in [JudgeStatus.JUDGING]:
                submission.result = self._update_status(submission)
        return self.success(self.paginate_data(request, submissions, SubmissionModelSerializer))

    # 目前主要是用于分数修改
    @admin_role_required
    def put(self, request):
        data = request.data
        user = request.user
        if "submission_id" not in data:
            return self.error("submission_id is needed")
        submission_id = data.pop("submission_id")
        try:
            submission = Submission.objects.get(id=submission_id)
        except Submission.DoesNotExist:
            return self.error("Submission not exist")
        if submission.contest:
            ensure_managed_by(submission.contest, user)
        else:
            ensure_created_by(submission.problem, user)

        for k, v in data.item:
            setattr(submission, k, v)
        submission.save()
        return self.success()
