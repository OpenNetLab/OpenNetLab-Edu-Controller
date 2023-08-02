from django.db.models import JSONField  # NOQA
from django.db import models
from utils.xss_filter import XSSHtml
import json


class RichTextField(models.TextField):
    def get_prep_value(self, value):
        with XSSHtml() as parser:
            return parser.clean(value or "")


class ListFeild(models.TextField):
    description = "Store a python list"

    def __init__(self, *args, **kwargs):
        super(ListFeild, self).__init__(*args, **kwargs)

    def to_python(self, value) -> list:
        if not value:
            value = []

        if isinstance(value, list):
            return value

        return json.loads(value)

    def get_prep_value(self, value) -> list:
        if not value:
            return value
        return None