from django.db import models
from django.utils import timezone


class JudgeServer(models.Model):
    hostname = models.JSONField(null=True)
    ip = models.TextField(null=True)
    available_ports = models.JSONField(default=list)
    using_ports = models.JSONField(default=list)
    available_ports_num = models.IntegerField(default=0)
    location = models.TextField(null=True)
    is_public = models.BooleanField(default=True)
    cpu_core = models.IntegerField(null=True)
    memory_usage = models.FloatField(null=True)
    cpu_usage = models.FloatField(null=True)
    last_heartbeat = models.DateTimeField(timezone.now())
    create_time = models.DateTimeField(auto_now_add=True)
    expired_time = models.DateTimeField(null=True)
    task_number = models.IntegerField(default=0)
    service_url = models.TextField(null=True)
    ca_pem = models.TextField(null=True)
    c_cert = models.TextField(null=True)
    c_key = models.TextField(null=True)
    is_ready = models.BooleanField(default=False)
    is_disabled = models.BooleanField(default=False)

    @property
    def status(self):
        # 增加一秒延时，提高对网络环境的适应性
        if (timezone.now() - self.last_heartbeat).total_seconds() > 60:
            return "abnormal"
        return "normal"

    class Meta:
        db_table = "judge_server"
