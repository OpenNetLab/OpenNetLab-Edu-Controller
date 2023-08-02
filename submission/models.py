from django.db import models

from utils.constants import ContestStatus
from utils.models import JSONField
from problem.models import Problem
from contest.models import Contest

from utils.shortcuts import rand_str


class JudgeStatus:
    COMPILE_ERROR = -2
    WRONG_ANSWER = -1
    ACCEPTED = 0
    RUNTIME_ERROR = 1
    SYSTEM_ERROR = 2
    NETWORK_TIMEOUT = 3
    PENDING = 4
    JUDGING = 5
    PARTIALLY_ACCEPTED = 6


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
    # 从JudgeServer返回的判题详情
    info = JSONField(default=dict)
    language = models.TextField()
    shared = models.BooleanField(default=False)
    # 存储该提交所用时间和内存值，方便提交列表显示
    # {time_cost: "", memory_cost: "", err_info: "", score: 0}
    ip = models.TextField(null=True)

    def check_user_permission(self, user, check_share=True):
        if self.user_id == user.id or user.is_super_admin() or user.can_mgmt_all_problem() or self.problem.created_by_id == user.id:
            return True

        if check_share:
            if self.contest and self.contest.status != ContestStatus.CONTEST_ENDED:
                return False
            if self.problem.share_submission or self.shared:
                return True
        return False

    def modify_permission(self, user, check_share=True):
        if user.is_super_admin() or (user.is_admin_role() and user.id in self.problem.contest.contest_admin):
            return True
        return False

    class Meta:
        db_table = "submission"
        ordering = ("-create_time",)

    def __str__(self):
        return self.id
