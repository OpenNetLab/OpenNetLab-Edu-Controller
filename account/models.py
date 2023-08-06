import uuid

from django.db import models
from django.contrib.auth.models import AbstractBaseUser

# Create your models here.
from utils.models import JSONField, ListFeild


class AdminType(object):
    REGULAR_USER = "Regular User" #student
    ADMIN = "Admin" # tutor
    SUPER_ADMIN = "Super Admin" #teacher

class ProblemPermission(object):
    NONE = "None"
    OWN = "Own"
    ALL = "All"

class UserManager(models.Manager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})

class User(AbstractBaseUser):
    #每次添加都会自动生成
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.TextField(unique=True)
    email = models.TextField(null=True, unique=True)
    create_time = models.DateTimeField(auto_now_add=True, null=True)
    #UserType
    admin_type = models.TextField(default=AdminType.REGULAR_USER)
    problem_permission = models.TextField(default=ProblemPermission.NONE)
    reset_password_token = models.TextField(null=True)
    reset_password_token_expire_time = models.DateTimeField(null=True)
    #SSO auth token
    auth_token = models.TextField(null=True)
    two_factor_auth = models.BooleanField(default=False)
    tfa_token = models.TextField(null=True)
    session_keys = JSONField(default=list)
    # open api key
    open_api = models.BooleanField(default=False)
    open_api_appkey = models.TextField(null=True)
    is_disabled = models.BooleanField(default=False)


    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    objects = UserManager() #

    def is_admin(self):
        return self.admin_type == AdminType.ADMIN

    def is_super_admin(self):
        return self.admin_type == AdminType.SUPER_ADMIN

    def is_admin_role(self):
        return self.admin_type in [AdminType.ADMIN, AdminType.SUPER_ADMIN]

    def can_mgmt_all_problem(self):
        return self.problem_permission == ProblemPermission.ALL

    def is_contest_admin(self, contest):
        return self.is_authenticated and (str(self.id) in contest.contest_admin or self.admin_type == AdminType.SUPER_ADMIN)

    class Meta:
        db_table = "user"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # dict of problem.id:max_grade
    problems_status = JSONField(default=dict)
    real_name = models.TextField(null=True)
    blog = models.URLField(null=True)
    github = models.TextField(null=True)
    school = models.TextField(null=True)
    major = models.TextField(null=True)
    language = models.TextField(null=True)
    # for Contest
    total_submissions = models.IntegerField(default=0)
    accepted_number = models.IntegerField(default=0)
    total_score = models.IntegerField(default=0)

    def add_accepted_problem_number(self):
        self.accepted_number = models.F("accepted_number") + 1
        self.save()

    def add_score(self, this_time_score, last_time_score=None):
        last_time_score = last_time_score or 0
        self.total_score = models.F("total_score") - last_time_score + this_time_score
        self.save()
    class Meta:
        db_table = "user_profile"
