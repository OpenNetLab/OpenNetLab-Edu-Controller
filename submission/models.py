from django.db import models

from utils.constants import ContestStatus
from utils.models import JSONField
from problem.models import Problem
from contest.models import Contest

from utils.shortcuts import rand_str


class JudgeStatus:
    PENDING = 0
    JUDGING = 1
    SYSTEM_ERROR = 2
    ALL_PASSED = 3
    SOME_PASSED = 4
    ALL_FAILED = 5
    PROGRAM_TIMEOUT = 6


class Submission(models.Model):
    id = models.TextField(default=rand_str, primary_key=True, db_index=True)
    contest = models.ForeignKey(Contest, null=True, on_delete=models.CASCADE)
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    create_time = models.DateTimeField(auto_now_add=True)
    user_id = models.CharField(db_index=True, max_length=50)
    username = models.TextField()
    code_list = models.JSONField(default=list)
    server_list = models.JSONField(default=list)
    ports_list = models.JSONField(default=dict)
    result = models.IntegerField(db_index=True, default=JudgeStatus.PENDING)
    grade = models.IntegerField(default=0)
    failed_info = JSONField(default=list)
    language = models.TextField()
    shared = models.BooleanField(default=False)
    ip = models.TextField(null=True)

    def check_user_permission(self, user, check_share=True):
        if (
            self.user_id == user.id
            or user.is_super_admin()
            or user.can_mgmt_all_problem()
            or self.problem.created_by_id == user.id
        ):
            return True

        if check_share:
            if self.contest and self.contest.status != ContestStatus.CONTEST_ENDED:
                return False
            if self.problem.share_submission or self.shared:
                return True
        return False

    def modify_permission(self, user, check_share=True):
        if user.is_super_admin() or (
            user.is_admin_role() and user.id in self.problem.contest.contest_admin
        ):
            return True
        return False

    class Meta:
        db_table = "submission"
        ordering = ("-create_time",)

    def __str__(self):
        return self.id
