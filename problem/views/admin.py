import json
import zipfile

from django.db.models import Q
from django.http import FileResponse

from account.decorators import problem_permission_required, ensure_created_by, ensure_managed_by
from contest.models import Contest, ContestStatus
from submission.models import Submission, JudgeStatus
from utils.api import APIView, validate_serializer
from utils.shortcuts import rand_str
from utils.tasks import delete_files
from judge.testing import ZipFileUploader, create_new_problem_from_template

from ..models import Problem, ProblemTag
from ..serializers import *

class ProblemBase(APIView):
    def common_checks(self, request):
        data = request.data
        

class ProblemFormBase(APIView):
    # use View's dispatch function
    request_parsers = None

class ProblemAPI(ProblemFormBase):
    # @validate_serializer(CreateProblemSerializer)
    @problem_permission_required
    def post(self, request):
        # construct problem data from WSGIRequest
        _id = request.POST.get("_id")
        if not _id:
            return self.error("Display ID is required")
        if Problem.objects.filter(_id=_id, contest_id__isnull=True).exists():
            return self.error("Display ID already exists")

        problem_data = {}
        # print(request.POST)
        str_fields = ["_id", "title", "description"]
        for field in str_fields:
            problem_data[field] = request.POST.get(field)
        problem_data["code_num"] = int(request.POST.get("code_num"))
        problem_data["code_names"] = request.POST.getlist("code_names")
        # print(problem_data)
        tags = request.POST.getlist("tags")
        problem_data["created_by"] = request.user
        problem = Problem.objects.create(**problem_data)

        uploader = ZipFileUploader(request.FILES.get('file'), problem)
        valid = uploader.upload()
        if not valid:
            return uploader.error_message

        # create inexist tags
        for item in tags:
            try:
                tag = ProblemTag.objects.get(name=item)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=item)
            problem.tags.add(tag)
        return self.success(ProblemAdminSerializer(problem).data)

    @problem_permission_required
    def get(self, request):
        problem_id = request.GET.get("id")
        user = request.user
        if problem_id:
            try:
                problem = Problem.objects.get(id=problem_id)
                ensure_created_by(problem, request.user)
                return self.success(ProblemAdminSerializer(problem).data)
            except Problem.DoesNotExist:
                return self.error("Problem does not exist")

        problems = Problem.objects.filter(contest_id__isnull=True).order_by("-create_time")

        keyword = request.GET.get("keyword", "").strip()
        if keyword:
            problems = problems.filter(Q(title__icontains=keyword) | Q(_id__icontains=keyword))
        if not user.can_mgmt_all_problem():
            problems = problems.filter(created_by=user)
        return self.success(self.paginate_data(request, problems, ProblemAdminSerializer))

    @problem_permission_required
    @validate_serializer(EditProblemSerializer)
    def put(self, request):
        data = request.data
        problem_id = data.pop("id")

        try:
            problem = Problem.objects.get(id=problem_id)
            ensure_created_by(problem, request.user)
        except Problem.DoesNotExist:
            return self.error("Problem does not exist")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Problem.objects.exclude(id=problem_id).filter(_id=_id, contest_id__isnull=True).exists():
            return self.error("Display ID already exists")

        # todo check filename and score info
        tags = data.pop("tags")

        for k, v in data.items():
            setattr(problem, k, v)
        problem.save()

        problem.tags.remove(*problem.tags.all())
        for tag in tags:
            try:
                tag = ProblemTag.objects.get(name=tag)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=tag)
            problem.tags.add(tag)

        return self.success()

    @problem_permission_required
    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid parameter, id is required")
        try:
            problem = Problem.objects.get(id=id, contest_id__isnull=True)
        except Problem.DoesNotExist:
            return self.error("Problem does not exists")
        ensure_created_by(problem, request.user)
        # d = os.path.join(settings.TEST_CASE_DIR, problem.test_case_id)
        # if os.path.isdir(d):
        #     shutil.rmtree(d, ignore_errors=True)
        problem.delete()
        return self.success()

class ContestProblemAPI(ProblemBase):
    @validate_serializer(AddContestProblemSerializer)
    def post(self, request):
        data = request.data
        try:
            contest = Contest.objects.get(id=data["contest_id"])
            problem = Problem.objects.get(id=data["problem_id"])
        except (Contest.DoesNotExist, Problem.DoesNotExist):
            return self.error("Contest or Problem does not exist")
        data["lab_id"] = data.pop("problem_id")
        data["contest"] = contest
        data["created_by"] = request.user
        if contest.status == ContestStatus.CONTEST_ENDED:
            return self.error("Contest has ended")
        if Problem.objects.filter(contest=contest, _id=data["display_id"]).exists():
            return self.error("Duplicate display id in this contest")
        if "title" not in data:
            data["title"] = problem.title
        if "description" not in data:
            data["description"] = problem.description
        data["visible"] = True
        if "hint" not in data:
            data["hint"] = problem.hint
        lab_config = data["lab_config"]
        data["lab_config"] = problem.lab_config
        if lab_config:
            for k, v in lab_config.items():
                if k in data["lab_config"].keys():
                    data["lab_config"][k] = v
        data["vm_num"] = problem.vm_num
        data["port_num"] = problem.port_num
        data["total_score"] = problem.total_score
        data["share_submission"] = False
        data["code_num"] = problem.code_num
        tags = problem.tags.all()
        data["_id"] = data.pop("display_id")
        data["is_public"] = True
        data["submission_number"] = data["accepted_number"] = 0
        problem = Problem.objects.create(**data)
        problem.tags.set(tags)
        return self.success(ProblemAdminSerializer(problem).data)

    def get(self, request):
        problem_id = request.GET.get("id")
        contest_id = request.GET.get("contest_id")
        user = request.user
        if problem_id:
            try:
                problem = Problem.objects.get(id=problem_id)
                ensure_managed_by(problem.contest, user)
            except Problem.DoesNotExist:
                return self.error("Problem does not exist")
            return self.success(ProblemAdminSerializer(problem).data)

        if not contest_id:
            return self.error("Contest id is required")
        try:
            contest = Contest.objects.get(id=contest_id)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")
        ensure_managed_by(contest, user)
        problems = Problem.objects.filter(contest=contest).order_by("-create_time")
        keyword = request.GET.get("keyword")
        if keyword:
            problems = problems.filter(title__contains=keyword)
        return self.success(self.paginate_data(request, problems, ProblemAdminSerializer))

    @validate_serializer(EditContestProblemSerializer)
    def put(self, request):
        data = request.data
        user = request.user

        try:
            contest = Contest.objects.get(id=data.pop("contest_id"))
            ensure_created_by(contest, user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")


        problem_id = data.pop("id")

        try:
            problem = Problem.objects.get(id=problem_id, contest=contest)
        except Problem.DoesNotExist:
            return self.error("Problem does not exist")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Problem.objects.exclude(id=problem_id).filter(_id=_id, contest=contest).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)
        # todo check filename and score info
        tags = data.pop("tags")

        for k, v in data.items():
            setattr(problem, k, v)
        problem.save()

        problem.tags.remove(*problem.tags.all())
        for tag in tags:
            try:
                tag = ProblemTag.objects.get(name=tag)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=tag)
            problem.tags.add(tag)
        return self.success()

    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid parameter, id is required")
        try:
            problem = Problem.objects.get(id=id, contest_id__isnull=False)
        except Problem.DoesNotExist:
            return self.error("Problem does not exists")
        ensure_created_by(problem.contest, request.user)

        #存在还在提交此题目的用户,后续可改为强制删除
        if Submission.objects.filter(problem=problem).exists():
            return self.error("Can't delete the problem as it has submissions")
        # d = os.path.join(settings.TEST_CASE_DIR, problem.test_case_id)
        # if os.path.isdir(d):
        #    shutil.rmtree(d, ignore_errors=True)
        problem.delete()
        return self.success()


class MakeContestProblemPublicAPIView(APIView):
    @validate_serializer(ContestProblemMakePublicSerializer)
    @problem_permission_required
    def post(self, request):
        data = request.data
        display_id = data.get("display_id")
        if Problem.objects.filter(_id=display_id, contest_id__isnull=True).exists():
            return self.error("Duplicate display ID")

        try:
            problem = Problem.objects.get(id=data["id"])
        except Problem.DoesNotExist:
            return self.error("Problem does not exist")

        if not problem.contest or problem.is_public:
            return self.error("Already be a public problem")
        problem.is_public = True
        problem.save()
        # https://docs.djangoproject.com/en/1.11/topics/db/queries/#copying-model-instances
        tags = problem.tags.all()
        problem.pk = None
        problem.contest = None
        problem._id = display_id
        problem.visible = False
        problem.submission_number = problem.accepted_number = 0
        problem.statistic_info = {}
        problem.save()
        problem.tags.set(tags)
        return self.success()

class AddContestProblemAPI(APIView):
    @validate_serializer(AddContestProblemSerializer)
    def post(self, request):
        data = request.data
        try:
            contest = Contest.objects.get(id=data["contest_id"])
            old_problem = Problem.objects.get(id=data["problem_id"])
        except (Contest.DoesNotExist, Problem.DoesNotExist):
            return self.error("Contest or Problem does not exist")
        data["lab_id"] = data.pop("problem_id")
        data["contest"] = contest
        data["created_by"] = request.user
        if contest.status == ContestStatus.CONTEST_ENDED:
            return self.error("Contest has ended")
        if Problem.objects.filter(contest=contest, _id=data["display_id"]).exists():
            return self.error("Duplicate display id in this contest")
        if "title" not in data:
            data["title"] = old_problem.title
        if "description" not in data:
            data["description"] = old_problem.description
        data["visible"] = True
        data["is_public"] = True
        data["code_num"] = old_problem.code_num
        data["code_names"] = old_problem.code_names
        
        tags = old_problem.tags.all()
        data["_id"] = data.pop("display_id")
        data["submission_number"] = data["accepted_number"] = 0
        new_problem = Problem.objects.create(**data)
        new_problem.tags.set(tags)

        create_new_problem_from_template(new_problem._id, old_problem._id)

        return self.success()


class ExportProblemAPI(APIView):
    def choose_answers(self, user, problem):
        ret = []
        for item in problem.languages:
            submission = Submission.objects.filter(problem=problem,
                                                   user_id=user.id,
                                                   language=item,
                                                   result=JudgeStatus.FINISHED).order_by("-create_time").first()
            if submission:
                ret.append({"language": submission.language, "code": submission.code})
        return ret

    def process_one_problem(self, zip_file, user, problem, index):
        info = ExportProblemSerializer(problem).data
        #提交语言以及Code详情(之后添加成绩字段)
        info["answers"] = self.choose_answers(user, problem=problem)
        compression = zipfile.ZIP_DEFLATED
        zip_file.writestr(zinfo_or_arcname=f"{index}/problem.json",
                          data=json.dumps(info, indent=4),
                          compress_type=compression)

    @validate_serializer(ExportProblemRequestSerialzier)
    def get(self, request):
        problems = Problem.objects.filter(id__in=request.data["problem_id"])
        for problem in problems:
            if problem.contest:
                ensure_managed_by(problem.contest, request.user)
            else:
                ensure_created_by(problem, request.user)
        path = f"/tmp/{rand_str()}.zip"
        with zipfile.ZipFile(path, "w") as zip_file:
            for index, problem in enumerate(problems):
                self.process_one_problem(zip_file=zip_file, user=request.user, problem=problem, index=index + 1)
        delete_files.send_with_options(args=(path,), delay=300_000)
        resp = FileResponse(open(path, "rb"))
        resp["Content-Type"] = "application/zip"
        resp["Content-Disposition"] = "attachment;filename=problem-export.zip"
        return resp
