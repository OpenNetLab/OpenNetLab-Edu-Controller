import dramatiq

from account.models import User
from submission.models import Submission
from utils.shortcuts import DRAMATIQ_WORKER_ARGS

from .dispatcher import JudgeDispatcher
from .testing import SubmissionTester


@dramatiq.actor(**DRAMATIQ_WORKER_ARGS())
def judge_task(submission_id, problem_id):
    uid = Submission.objects.get(id=submission_id).user_id
    if User.objects.get(id=uid).is_disabled:
        return
    JudgeDispatcher(submission_id, problem_id).judge()
    

@dramatiq.actor(**DRAMATIQ_WORKER_ARGS())
def local_judge_task(submission_id, problem_id):
    uid = Submission.objects.get(id=submission_id).user_id
    if User.objects.get(id=uid).is_disabled:
        return
    SubmissionTester(submission_id, problem_id).judge()
