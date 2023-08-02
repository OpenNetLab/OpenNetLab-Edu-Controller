# coding=utf-8
import os
from utils.shortcuts import get_env

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# use sqlite
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': "onl.db",
    }
}
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql_psycopg2',
#         'HOST': '127.0.0.1',
#         'PORT': 5435,
#         'NAME': "onlinejudge",
#         'USER': "onlinejudge",
#         'PASSWORD': 'onlinejudge'
#     }
# }

REDIS_CONF = {
    "host": '127.0.0.1',
    "port": 6380
}


DEBUG = True

ALLOWED_HOSTS = ["*"]

DATA_DIR = f"{BASE_DIR}/data"
