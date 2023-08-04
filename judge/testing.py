import zipfile
import os
import shutil
import subprocess
from os.path import isdir, join, exists, dirname
from django.core.files.storage import FileSystemStorage

from onl.settings import DATA_DIR
from problem.models import Problem
from submission.models import Submission


PROBLEM_DIR = "problems"
SUBMISSION_DIR = "submissions"
ZIPFILE_DIR = "zips"


class PathManager:
    @staticmethod
    def problem_dir(problem_id: str) -> str:
        return join(DATA_DIR, PROBLEM_DIR, problem_id)

    @staticmethod
    def submission_dir(submission_id: str) -> str:
        return join(DATA_DIR, SUBMISSION_DIR, submission_id)

    @staticmethod
    def zipfile_path(problem_id: str, zipfile_name: str) -> str:
        return join(DATA_DIR, ZIPFILE_DIR, problem_id, zipfile_name)


class ZipFileUploader:
    def __init__(self, uploaded_file, problem: Problem):
        if uploaded_file:
            fs = FileSystemStorage()
            self.zip_file_path = PathManager.zipfile_path(problem._id, uploaded_file.name)
            parnet_dir = dirname(self.zip_file_path)
            if not exists(parnet_dir):
                os.makedirs(parnet_dir)
            fs.save(self.zip_file_path, uploaded_file)
        else:
            raise Exception("zipfile is None")
        self.problem = problem
        self.problem_dir_path = PathManager.problem_dir(problem._id)
        if not exists(self.problem_dir_path):
            os.makedirs(self.problem_dir_path)
        self._error_message: str = ""

    @property
    def error_message(self):
        return self._error_message

    def check_files_in_dir(self, dir_path: str) -> bool:
        filenames = os.listdir(dir_path)
        for code_name in self.problem.code_names:
            if code_name not in filenames:
                self._error_message = f"file {code_name} not in zipfile uploaded"
                return False
        if "tester" not in filenames:
            self._error_message = "tester not in zipfile uploaded"
            return False
        if "testcases.json" not in filenames:
            self._error_message = "testcases.json not in zipfile uploaded"
            return False
        return True

    def upload(self) -> bool:
        with zipfile.ZipFile(self.zip_file_path, "r") as zip_ref:
            zip_ref.extractall(self.problem_dir_path)
        # check validity of extracted files
        # case 1 : onl/data/lab_templates/problem_id/files
        # case 2 : onl/data/lab_templates/problem_id/extracted_dir/files
        filenames = os.listdir(self.problem_dir_path)
        valid = True
        if len(filenames) == 0:
            valid = False
            self._error_message = f"error: {self.problem_dir_path} has nothing"
            pass
        elif len(filenames) == 1:
            dir = filenames[0]
            if not isdir(join(self.problem_dir_path, dir)):
                self._error_message = "unknown error: only one file in extracted dir"
                valid = False
            else:
                addtional_dir = join(self.problem_dir_path, dir)
                valid = self.check_files_in_dir(addtional_dir)
                if valid:
                    print(f"extract to addtional dir {addtional_dir}")
                    for filename in os.listdir(addtional_dir):
                        shutil.move(join(addtional_dir, filename), self.problem_dir_path)
                    shutil.rmtree(addtional_dir)
                    print(f"remove {addtional_dir}")
        else:
            valid = self.check_files_in_dir(self.problem_dir_path)

        if not valid:
            print(self._error_message)
            shutil.rmtree(self.problem_dir_path)
            print(f"remove {self.problem_dir_path}")
        shutil.rmtree(dirname(self.zip_file_path))
        print(f"remove {dirname(self.zip_file_path)}")

        return valid


class SubmissionTester:
    def __init__(self, submit_id: str, problem_id: str):
        self.submit_id = submit_id
        self.problem_id = problem_id
        self.submission_dir_path = PathManager.submission_dir(submit_id)
        if not exists(self.submission_dir_path):
            os.makedirs(self.submission_dir_path, exist_ok=True)

    def judge(self):
        tester = join(self.submission_dir_path, "tester")
        if not exists(tester):
            raise Exception(f"running submission: tester {tester} not exists")
        subprocess.run([tester, '--log', '--json'])
