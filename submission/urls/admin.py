from django.conf.urls import url

from ..views.admin import SubmissionRejudgeAPI, SubmissionAPI

urlpatterns = [
    url(r"^submission/rejudge?$", SubmissionRejudgeAPI.as_view(), name="submission_rejudge_api"),
    url(r"^submission/?$", SubmissionAPI.as_view(), name="submission_admin_api")
]
