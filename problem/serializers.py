import re

from django import forms

from options.options import SysOptions
from utils.api import UsernameSerializer, serializers
from options.options import SysOptions
from utils.api import UsernameSerializer, serializers
from utils.serializers import LanguageNameMultiChoiceField, SPJLanguageNameChoiceField, LanguageNameChoiceField

from .models import Problem, ProblemTag
from .utils import parse_problem_template

class DockerImageUploadForm(forms.Form):
    config = forms.CharField(max_length=100)
    file = forms.FileField()



class CreateProblemCodeTemplateSerializer(serializers.Serializer):
    pass


class CreateOrEditProblemSerializer(serializers.Serializer):
    _id = serializers.CharField(max_length=32, allow_blank=True, allow_null=True)
    title = serializers.CharField(max_length=1024)
    description = serializers.CharField()
    code_num = serializers.IntegerField(min_value=1)
    code_names = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=32), allow_empty=False)
    # hint = serializers.CharField(allow_blank=True, allow_null=True)
    # share_submission = serializers.BooleanField(default=False)
    languages = LanguageNameMultiChoiceField()
    # lab_config = serializers.JSONField()
    # total_score = serializers.IntegerField(default=0)
    # visible = serializers.BooleanField(default=True)
    # vm_num = serializers.IntegerField(min_value=1)
    # port_num = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)

class CreateProblemSerializer(CreateOrEditProblemSerializer):
    pass


class EditProblemSerializer(CreateOrEditProblemSerializer):
    id = serializers.IntegerField()

class CreateContestProblemSerializer(CreateOrEditProblemSerializer):
    lab_id = serializers.IntegerField()
    lab_config = serializers.JSONField(allow_null=True)
    contest_id = serializers.IntegerField()


class EditContestProblemSerializer(CreateOrEditProblemSerializer):
    id = serializers.IntegerField()
    lab_id = serializers.IntegerField(allow_null=True)
    lab_config = serializers.JSONField(allow_null=True)
    contest_id = serializers.IntegerField()


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProblemTag
        fields = "__all__"

class BaseProblemSerializer(serializers.ModelSerializer):
    tags = serializers.SlugRelatedField(many=True, slug_field="name", read_only=True)
    created_by = UsernameSerializer()



class ProblemAdminSerializer(BaseProblemSerializer):
    class Meta:
        model = Problem
        fields = "__all__"


class ProblemSerializer(BaseProblemSerializer):

    class Meta:
        model = Problem
        exclude = ("visible", "is_public")


class ProblemSafeSerializer(BaseProblemSerializer):

    class Meta:
        model = Problem
        exclude = ("visible", "is_public", "submission_number", "accepted_number", "statistic_info")

class ContestProblemMakePublicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display_id = serializers.CharField(max_length=32)

class ExportProblemSerializer(serializers.ModelSerializer):
    display_id = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    hint = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    tags = serializers.SlugRelatedField(many=True, slug_field="name", read_only=True)

    def get_display_id(self, obj):
        return obj._id

    def _html_format_value(self, value):
        return {"format": "html", "value": value}

    def get_description(self, obj):
        return self._html_format_value(obj.description)

    def get_hint(self, obj):
        return self._html_format_value(obj.hint)

    def get_source(self, obj):
        return obj.source or f"{SysOptions.website_name} {SysOptions.website_base_url}"

    class Meta:
        model = Problem
        fields = ("display_id", "title", "description", "tags", "hint")

class AddContestProblemSerializer(serializers.Serializer):
    contest_id = serializers.IntegerField()
    problem_id = serializers.IntegerField()
    display_id = serializers.CharField()
    lab_config = serializers.JSONField()


class ExportProblemRequestSerialzier(serializers.Serializer):
    problem_id = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class UploadProblemForm(forms.Form):
    file = forms.FileField()


class FormatValueSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=["html", "markdown"])
    value = serializers.CharField(allow_blank=True)

class AnswerSerializer(serializers.Serializer):
    code = serializers.CharField()
    language = LanguageNameChoiceField()

class ImportProblemSerializer(serializers.Serializer):
    display_id = serializers.CharField(max_length=128)
    title = serializers.CharField(max_length=128)
    description = FormatValueSerializer()
    input_description = FormatValueSerializer()
    output_description = FormatValueSerializer()
    hint = FormatValueSerializer()
    answers = serializers.ListField(child=AnswerSerializer())
    tags = serializers.ListField(child=serializers.CharField())
