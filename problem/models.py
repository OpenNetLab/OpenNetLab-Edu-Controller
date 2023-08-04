from django.db import models
from utils.models import JSONField, ListFeild

from account.models import User
from contest.models import Contest
from utils.models import RichTextField
from utils.constants import Choices


class ProblemTag(models.Model):
    name = models.TextField()

    class Meta:
        db_table = "problem_tag"

class Problem(models.Model):
    # display ID
    _id = models.TextField(db_index=True)
    contest = models.ForeignKey(Contest, null=True, on_delete=models.CASCADE)
    # for contest problem
    lab_id = models.IntegerField(null=True)
    # lab_config = models.JSONField(default=dict)
    is_public = models.BooleanField(default=True)
    title = models.TextField()
    # code segment filenames to be substituded
    description = RichTextField()
    # hint = RichTextField(null=True)
    languages = JSONField(default=["python"])
    #需要的节点数量
    vm_num = models.IntegerField(default=1)
    #各个节点所需要的端口数量
    port_num = models.JSONField(default=list)
    #学生需要编写的代码段数量
    code_num = models.IntegerField()
    code_names = models.JSONField()
    template = JSONField(null=True)
    create_time = models.DateTimeField(auto_now_add=True)
    # we can not use auto_now here
    last_update_time = models.DateTimeField(null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)

    # judge related
    visible = models.BooleanField(default=True)
    tags = models.ManyToManyField(ProblemTag)
    total_score = models.IntegerField(default=0)
    submission_number = models.BigIntegerField(default=0)
    accepted_number = models.BigIntegerField(default=0)
    # {JudgeStatus.ACCEPTED: 3, JudgeStaus.WRONG_ANSWER: 11}, the number means count
    statistic_info = JSONField(default=dict)
    share_submission = models.BooleanField(default=False)

    class Meta:
        db_table = "problem"
        unique_together = (("_id", "contest"),)
        ordering = ("create_time",)

    def add_submission_number(self):
        self.submission_number = models.F("submission_number") + 1
        self.save(update_fields=["submission_number"])

    def add_ac_number(self):
        self.accepted_number = models.F("accepted_number") + 1
        self.save(update_fields=["accepted_number"])

