import json
import zipfile
import os
import shutil
import shlex
import subprocess
from os.path import isdir, join, exists, dirname
from django.core.files.storage import FileSystemStorage

from onl.settings import DATA_DIR
from problem.models import Problem
from submission.models import JudgeStatus, Submission


PROBLEM_DIR = "problems"
SUBMISSION_DIR = "submissions"
ZIPFILE_DIR = "zips"

TESTCASE_NAME = "testcases.json"
TESTER_NAME = "tester"

class TestResult:
    Succeed = 0
    Error   = 1
    Timeout = 2

def create_new_problem_from_template(new_problem_id: int, old_problem_id: int):
    old_path = PathManager.problem_dir(old_problem_id)
    new_path = PathManager.problem_dir(new_problem_id)
    os.makedirs(new_path, exist_ok=True)
    for filename in os.listdir(old_path):
        filepath = join(old_path, filename)
        if isdir(filepath):
            continue
        shutil.copy2(filepath, new_path)
    print(f'create problem instance {new_path}')

def make_file_executable(file_path):
    try:
        # Define the executable permission in octal format (e.g., 0o755).
        # This gives read, write, and execute permissions to the owner,
        # and read and execute permissions to the group and others.
        executable_permission = 0o755

        # Change the file's permission to make it executable.
        os.chmod(file_path, executable_permission)
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def run_command_with_timeout(command: list, timeout: float) -> int:
    try:
        # Use the 'sudo' command to execute the given command with elevated privileges.
        result = subprocess.run(["/usr/bin/python3"] + command, capture_output=True, text=True, check=True, timeout=timeout)
        # print("Command output:\n", result.stdout)
        return TestResult.Succeed
    except subprocess.TimeoutExpired:
        print(f'program timeout after {timeout} seconds')
        return TestResult.Timeout
    except subprocess.CalledProcessError as e:
        print("Command execution failed.")
        print(f"Error: {e}")
        return TestResult.Error


class PathManager:
    @staticmethod
    def problem_dir(id: int) -> str:
        return join(DATA_DIR, PROBLEM_DIR, str(id))

    @staticmethod
    def submission_dir(user_id: str, submission_id: str) -> str:
        return join(DATA_DIR, SUBMISSION_DIR, user_id, submission_id)

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
        self.problem_dir_path = PathManager.problem_dir(problem.id)
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
        if "logs" in filenames and isdir(join(dir_path, "logs")):
            self._error_message = "lab zip cannot include logs directory"
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

        make_file_executable(join(self.problem_dir_path, TESTER_NAME))

        return valid


class SubmissionTester:
    def __init__(self, submission: Submission):
        self.sub = submission
        self.sub_dirpath = PathManager.submission_dir(str(submission.user_id), submission.id)
        if not exists(self.sub_dirpath):
            os.makedirs(self.sub_dirpath, exist_ok=True)
        problem: Problem = submission.problem
        prob_dir = PathManager.problem_dir(problem.id) # use display id
        if not exists(prob_dir):
            raise Exception("problem dir {} not exists".format(prob_dir))
        for filename in os.listdir(prob_dir):
            filepath = join(prob_dir, filename)
            if isdir(filepath):
                continue
            shutil.copy2(filepath, self.sub_dirpath)
        for index, codename in enumerate(problem.code_names):
            filecontent = submission.code_list[index]
            codepath = join(self.sub_dirpath, codename)
            with open(codepath, "w") as wfp:
                print(f"substitude {codepath} with user implemented")
                wfp.write(filecontent)

    def remove_all_logs(self):
        log_path = join(self.sub_dirpath, 'logs')
        if not exists(log_path):
            return
        for filename in os.listdir(log_path):
            if filename.startswith("testcase"):
                file_path = join(log_path, filename)
                os.remove(file_path)

    def remove_redudant_logs(self, failed_indexes: list):
        log_path = join(self.sub_dirpath, 'logs')
        ignore_files = [f"testcase{idx}.log" for idx in failed_indexes]
        ignore_files.append("results.json")
        for filename in os.listdir(log_path):
            if filename in ignore_files:
                continue
            file_path = join(log_path, filename)
            os.remove(file_path)

    def trim_logs(self, failed_indexes: list):
        log_path = join(self.sub_dirpath, 'logs')
        max_lines = 1000
        for idx in failed_indexes:
            file_path = join(log_path, f"testcase{idx}.log")
            temp_file_path = file_path + ".trimmed"
            escaped_file_path = shlex.quote(file_path)
            tail_command = f"tail -n {max_lines} {escaped_file_path} > {shlex.quote(temp_file_path)}"
            os.system(tail_command)

            with open(temp_file_path, 'r') as temp_file:
                content = temp_file.read()

            if os.path.getsize(file_path) > os.path.getsize(temp_file_path):
                with open(temp_file_path, 'w') as temp_file:
                    temp_file.write("log file is too long, only show the last 1000 lines:\n")
                    temp_file.write(content)

            os.remove(file_path)
            os.rename(temp_file_path, file_path)


    def judge(self) -> bool:
        # return True if grade is 100
        tester_path = join(self.sub_dirpath, TESTER_NAME)
        if not exists(tester_path):
            raise Exception("running submission: tester {} not exists".format(tester_path))
        print(f"running {tester_path}")
        res = run_command_with_timeout([tester_path, "--log", "--json"], self.sub.problem.timeout)

        if res == TestResult.Timeout:
            self.sub.result = JudgeStatus.PROGRAM_TIMEOUT
            self.sub.save()
            return False
        elif res != TestResult.Succeed:
            self.remove_all_logs()
            self.sub.result = JudgeStatus.ALL_FAILED
            self.sub.save()
            return False
        elif res == TestResult.Error:
            raise Exception("Running test proc has some problem")

        log_path = join(self.sub_dirpath, 'logs')
        if not exists(log_path):
            raise Exception(f"logs path {log_path} not exists")
        failed_info = []
        failed_indexes: list

        with open(join(log_path, "results.json")) as fp:
            res = json.load(fp)
            grade = res['grade']
            self.sub.grade = res['grade']

            if grade == 0 or grade == 100:
                self.remove_all_logs()
            else:
                # clean and trim
                failed_indexes = res['failed']
                self.remove_redudant_logs(failed_indexes)
                self.trim_logs(failed_indexes)

                for idx in res['failed']:
                    log_fp = open(join(log_path, f"testcase{idx}.log"), "r")
                    testcase_fp = open(join(self.sub_dirpath, TESTCASE_NAME), "r")
                    testcase_json_data = json.load(testcase_fp)
                    # notice the index here, logical index starts from 1
                    if "config" in testcase_json_data:
                        # global config
                        config = testcase_json_data["config"]
                    else:
                        cur_data = testcase_json_data["testcases"][idx-1] 
                        if "config" in cur_data:
                            # specific config for testcase
                            config = cur_data["config"]
                        else:
                            # no config
                            config = None
                    displayed_test = {
                        "input": testcase_json_data["testcases"][idx-1]["input"],
                        "expected_output":testcase_json_data["testcases"][idx-1]["output"],
                    }
                    # config, "testcase"
                    failed_info.append({
                        "config": config,
                        "testcase_index": idx,
                        "testcase": displayed_test,
                        "log": log_fp.read()
                    })
                    log_fp.close()
                    testcase_fp.close()

        self.sub.failed_info = failed_info
        if grade == 0:
            self.sub.result = JudgeStatus.ALL_FAILED
        elif grade == 100:
            self.sub.result = JudgeStatus.ALL_PASSED
        else:
            self.sub.result = JudgeStatus.SOME_PASSED
        self.sub.save()

        if grade == 100:
            return True
        return False
