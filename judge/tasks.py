import dramatiq

from account.models import User, UserProfile
from submission.models import Submission
from problem.models import Problem
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
def local_judge_task(submission_id, problem_id, user_id):
    submission = Submission.objects.get(id=submission_id)

    problem = Problem.objects.get(_id=problem_id)
    problem.submission_number += 1
    try:
        if SubmissionTester(submission).judge():
            problem.accepted_number += 1
    except Exception as e:
        raise
    problem.save()

    score = submission.grade
    user = User.objects.get(id=user_id)
    assert user
    profile = UserProfile.objects.get(user=user)
    assert profile
    profile.total_submissions += 1
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
