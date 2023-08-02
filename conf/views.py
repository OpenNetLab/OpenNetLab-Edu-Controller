import hashlib
import json
import os
import re
import shutil
import smtplib
import time
from datetime import datetime

import pytz
import json
import requests
from django.conf import settings
from django.utils import timezone
from requests.exceptions import RequestException

from account.decorators import super_admin_required
from account.models import User
from contest.models import Contest
from judge.dispatcher import process_pending_task
from options.options import SysOptions
from problem.models import Problem
from submission.models import Submission
from utils.api import APIView, CSRFExemptAPIView, validate_serializer
from utils.shortcuts import send_email, get_env
from utils.xss_filter import XSSHtml
from .models import JudgeServer
from .serializers import (CreateEditWebsiteConfigSerializer,
                          CreateSMTPConfigSerializer, EditSMTPConfigSerializer,
                          JudgeServerHeartbeatSerializer,
                          JudgeServerSafeSerializer, TestSMTPConfigSerializer, EditJudgeServerSerializer)


class SMTPAPI(APIView):
    @super_admin_required
    def get(self, request):
        smtp = SysOptions.smtp_config
        if not smtp:
            return self.success(None)
        smtp.pop("password")
        return self.success(smtp)

    @super_admin_required
    @validate_serializer(CreateSMTPConfigSerializer)
    def post(self, request):
        SysOptions.smtp_config = request.data
        return self.success()

    @super_admin_required
    @validate_serializer(EditSMTPConfigSerializer)
    def put(self, request):
        smtp = SysOptions.smtp_config
        data = request.data
        for item in ["server", "port", "email", "tls"]:
            smtp[item] = data[item]
        if "password" in data:
            smtp["password"] = data["password"]
        SysOptions.smtp_config = smtp
        return self.success()


class SMTPTestAPI(APIView):
    @super_admin_required
    @validate_serializer(TestSMTPConfigSerializer)
    def post(self, request):
        if not SysOptions.smtp_config:
            return self.error("Please setup SMTP config at first")
        try:
            send_email(smtp_config=SysOptions.smtp_config,
                       from_name=SysOptions.website_name_shortcut,
                       to_name=request.user.username,
                       to_email=request.data["email"],
                       subject="You have successfully configured SMTP",
                       content="You have successfully configured SMTP")
        except smtplib.SMTPResponseException as e:
            # guess error message encoding
            msg = b"Failed to send email"
            try:
                msg = e.smtp_error
                # qq mail
                msg = msg.decode("gbk")
            except Exception:
                msg = msg.decode("utf-8", "ignore")
            return self.error(msg)
        except Exception as e:
            msg = str(e)
            return self.error(msg)
        return self.success()


class WebsiteConfigAPI(APIView):
    def get(self, request):
        ret = {key: getattr(SysOptions, key) for key in
               ["website_base_url", "website_name", "website_name_shortcut",
                "website_footer", "allow_register", "submission_list_show_all"]}
        return self.success(ret)

    @super_admin_required
    @validate_serializer(CreateEditWebsiteConfigSerializer)
    def post(self, request):
        for k, v in request.data.items():
            if k == "website_footer":
                with XSSHtml() as parser:
                    v = parser.clean(v)
            setattr(SysOptions, k, v)
        return self.success()

#资源节点API
class JudgeServerAPI(APIView):
    @super_admin_required
    def get(self, request):
        servers = JudgeServer.objects.all().order_by("id")
        return self.success({"token": SysOptions.judge_server_token,
                             "servers": JudgeServerSafeSerializer(servers, many=True).data})

    @super_admin_required
    def delete(self, request):
        hostname = request.GET.get("hostname")
        if hostname:
            JudgeServer.objects.filter(hostname=hostname).delete()
        return self.success()

    #只用来更新资源节点可用性，配置信息在心跳检测进行更新
    @validate_serializer(EditJudgeServerSerializer)
    @super_admin_required
    def put(self, request):
        is_disabled = request.data.get("is_disabled", False)
        JudgeServer.objects.filter(id=request.data["id"]).update(is_disabled=is_disabled)
        if not is_disabled:
            process_pending_task()
        return self.success()

#心跳检测， 检测到新资源节点自动进行资源创建
class JudgeServerHeartbeatAPI(CSRFExemptAPIView):
    @validate_serializer(JudgeServerHeartbeatSerializer)
    def post(self, request):
        data = request.data
        #Ready参数无法传入Fix_me
        if "ready" not in data:
            data["ready"] = False
        #验证JudgeServer Token
        client_token = request.META.get("HTTP_X_JUDGE_SERVER_TOKEN")
        if hashlib.sha256(SysOptions.judge_server_token.encode("utf-8")).hexdigest() != client_token:
            return self.error("Invalid token")
        #JudgeServer 信息实时更新
        try:
            server = JudgeServer.objects.get(ip=request.ip)
            # tls renew
            if "c_cert" in data:
                server.ca_pem = data["ca_pem"],
                server.c_cert = data["c_cert"],
                server.c_key = data["c_key"],
                server.save(update_fields=["ca_pem", "c_cert", "c_key"])

            server.cpu_core = data["cpu_core"]
            server.using_ports = data["using_ports"]
            server.available_ports = list(set(data["available_ports"]) - set(data["using_ports"]))
            server.available_ports_num = len(data["available_ports"]) - len(data["using_ports"])
            server.location = data["location"]
            server.memory_usage = data["memory_usage"]
            server.cpu_usage = data["cpu_usage"]
            server.service_url = data["service_url"]
            server.ip = request.ip
            server.is_ready = data["is_ready"]
            server.last_heartbeat = timezone.now()
            server.save(update_fields=["cpu_core", "ip", "using_ports", "available_ports", "available_ports_num", "location",
                                       "memory_usage", "cpu_usage", "service_url", "ip", "is_ready", "last_heartbeat"])
        except JudgeServer.DoesNotExist:
            server = JudgeServer.objects.create(hostname=data["hostname"],
                                       ca_pem=data["ca_pem"],
                                       c_cert=data["c_cert"],
                                       c_key=data["c_key"],
                                       cpu_core=data["cpu_core"],
                                       using_ports=data["using_ports"],
                                       available_ports=list(set(data["available_ports"]) - set(data["using_ports"])),
                                       available_ports_num=len(data["available_ports"]) - len(data["using_ports"]),
                                       location=data["location"],
                                       memory_usage=data["memory_usage"],
                                       cpu_usage=data["cpu_usage"],
                                       ip=request.META["REMOTE_ADDR"],
                                       service_url=data["service_url"],
                                       last_heartbeat=timezone.now(),
                                       is_ready=data["ready"],
                                       )
        # 新server上线 处理队列中的，防止没有新的提交而导致一直waiting
        process_pending_task()

        return self.success(JudgeServerSafeSerializer(server).data)


class LanguagesAPI(APIView):
    def get(self, request):
        return self.success({"languages": SysOptions.languages, "spj_languages": SysOptions.spj_languages})


class TestCasePruneAPI(APIView):
    @super_admin_required
    def get(self, request):
        """
        return orphan test_case list
        """
        ret_data = []
        dir_to_be_removed = self.get_orphan_ids()

        # return an iterator
        for d in os.scandir(settings.TEST_CASE_DIR):
            if d.name in dir_to_be_removed:
                ret_data.append({"id": d.name, "create_time": d.stat().st_mtime})
        return self.success(ret_data)

    @super_admin_required
    def delete(self, request):
        test_case_id = request.GET.get("id")
        if test_case_id:
            self.delete_one(test_case_id)
            return self.success()
        for id in self.get_orphan_ids():
            self.delete_one(id)
        return self.success()

    @staticmethod
    def get_orphan_ids():
        db_ids = Problem.objects.all().values_list("test_case_id", flat=True)
        disk_ids = os.listdir(settings.TEST_CASE_DIR)
        test_case_re = re.compile(r"^[a-zA-Z0-9]{32}$")
        disk_ids = filter(lambda f: test_case_re.match(f), disk_ids)
        return list(set(disk_ids) - set(db_ids))

    @staticmethod
    def delete_one(id):
        test_case_dir = os.path.join(settings.TEST_CASE_DIR, id)
        if os.path.isdir(test_case_dir):
            shutil.rmtree(test_case_dir, ignore_errors=True)


class ReleaseNotesAPI(APIView):
    def get(self, request):
        try:
            resp = requests.get("https://raw.githubusercontent.com/QingdaoU/OnlineJudge/master/docs/data.json?_=" + str(time.time()),
                                timeout=3)
            releases = resp.json()
        except (RequestException, ValueError):
            return self.success()
        with open("docs/data.json", "r") as f:
            local_version = json.load(f)["update"][0]["version"]
        releases["local_version"] = local_version
        return self.success(releases)


class DashboardInfoAPI(APIView):
    def get(self, request):
        today = datetime.today()
        today_submission_count = Submission.objects.filter(
            create_time__gte=datetime(today.year, today.month, today.day, 0, 0, tzinfo=pytz.UTC)).count()
        recent_contest_count = Contest.objects.exclude(end_time__lt=timezone.now()).count()
        judge_server_count = len(list(filter(lambda x: x.status == "normal", JudgeServer.objects.all())))
        return self.success({
            "user_count": User.objects.count(),
            "recent_contest_count": recent_contest_count,
            "today_submission_count": today_submission_count,
            "judge_server_count": judge_server_count,
            "env": {
                "FORCE_HTTPS": get_env("FORCE_HTTPS", default=False),
                "STATIC_CDN_HOST": get_env("STATIC_CDN_HOST", default="")
            }
        })
