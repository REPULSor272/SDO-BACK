import ast
import contextlib
from enum import IntEnum
import io
import threading
import time
import re
from typing import List, Dict

import requests

import json

from app.config.settings import CSAppSettings, get_settings
from app.db.task_methods import get_test_cases_by_task, update_solution_test_result
from  app.schemas.tests import TestCase

class SubjectTypes(IntEnum):
    Python = 1
    CSharp = 4

class TeacherList:
    variables = dict()
    input_variables = []
    formulas_teacher = dict()
    formulas_student = dict()
    check = []
    operations_in_math = ['+', '-', '/', '*', '=']

    def __int__(self, variables, formulas):
        self.variables = variables
        self.formulas = formulas

    def binding_variables(self, a, b):  # a - student variable, b - teacher variable
        buff = dict()
        for i in range(0, len(self.variables)):
            if b == list(self.variables.items())[i][1]:
                buff[a] = b
            else:
                buff[list(self.variables.items())[i][0]] = list(self.variables.items())[i][1]
        self.variables = buff

    def binding_formulas(self, a, b):  # a - student formula, b - teacher formula
        for i in range(0, len(self.formulas_teacher)):
            if b == list(self.formulas_teacher.items())[i][1]:
                self.formulas_student[i] = a

    def add_variable(self, a):
        flag = False
        for i in range(0, len(self.variables)):
            if a == self.variables[i]:
                flag = True
        if not flag:
            self.variables[len(self.variables)] = a

    def add_teacher_formula(self, a):
        buff = []
        for char1 in a:
            for char2 in self.operations_in_math:
                if char1 == char2:
                    buff.append(a[:a.find(char2)])
                    self.add_variable(a[:a.find(char2)])
                    buff.append(char2)
                    a = a[a.find(char2) + 1:]
        buff.append(a)
        self.add_variable(a)
        self.formulas_teacher[len(self.formulas_teacher)] = buff
        self.check.append(False)

    def normalize_formula(self, formula: str) -> str:
        var_regex = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')
        normalized = formula
        var_map: Dict[str, str] = {}
        var_count = 0

        for match in var_regex.finditer(formula):
            match_str = match.group()
            if match_str not in var_map:
                var_map[match_str] = f"VAR{var_count}"
                var_count += 1

        for original, replacement in var_map.items():
            normalized = re.sub(r'\b' + original + r'\b', replacement, normalized)

        normalized = normalized.replace(' ', '')
        if normalized.endswith(';'):
            normalized = normalized[:-1]

        return normalized

    def extract_expressions(self, line: str) -> List[str]:
        expr_regex = re.compile(r'([\w\s\+\-\*/\^\=()]+)')
        expressions = []

        for match in expr_regex.finditer(line):
            expr = match.group(1).strip()
            if any(op in expr for op in '+-*/=^'):
                expressions.append(expr)

        return expressions

    def add_student_formula(self, line):
        normalized_input = self.normalize_formula("".join(self.formulas_teacher[0]))
        found = False

        line = line.rstrip('\n')
        if line.endswith(';'):
            line = line[:-1]

        for i in self.formulas_teacher:
            expressions = self.extract_expressions(line)
            for expr in expressions:
                normalized_line = self.normalize_formula(expr)
                if normalized_input == normalized_line:
                    found = True
                    break

                if found:
                    break

            if found:
                self.binding_variables(line, self.formulas_teacher[i])
                self.binding_formulas(line, self.formulas_teacher[i])

async def check_formulas(teacher_formula_str, input_variables_str, code_str) -> tuple[str, bool]:
    teacher_list = TeacherList()
    for line in teacher_formula_str.splitlines():
        line = line.rstrip()
        teacher_list.add_teacher_formula(line)

    for line in input_variables_str.splitlines():
        line = line.rstrip()
        teacher_list.input_variables.append(line)

    input_count = 0
    for line in code_str.splitlines():
        line = line.rstrip()
        if 'input()' in line:
            char = line[:line.find('=')].strip()
            teacher_list.binding_variables(char, teacher_list.input_variables[input_count])
            input_count += 1
        else:
            teacher_list.add_student_formula(line)

    res = ""
    all_formulas_correct = True
    for i in range(len(teacher_list.formulas_teacher)):
        if i in teacher_list.formulas_student:
            student_formula = "".join(teacher_list.formulas_student[i])
            teacher_formula = "".join(teacher_list.formulas_teacher[i])
            if student_formula != teacher_formula:
                all_formulas_correct = False
            res += student_formula + '\n'
        else:
            all_formulas_correct = False

    return res, all_formulas_correct


def _count_code_lines(code_str: str) -> int:
    return sum(1 for line in code_str.split('\n') if line.strip())


def _count_python_variables(code_str: str) -> int | None:
    """Число уникальных имён, которым в коде что-то присваивается.

    Считаются: присваивания (в т.ч. множественные), +=, аннотированные,
    переменные циклов for и генераторов, with ... as, :=.
    Не считаются: параметры функций, имена функций/классов, атрибуты (self.x).
    При синтаксической ошибке возвращает None.
    """
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return None
    return len({
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    })


def _limit_fail(message: str, code_length: int | None = None) -> dict:
    return {
        "test_case_number": 0,
        "input_data": "",
        "user_output": message,
        "expected_output": "",
        "status": "Failed",
        "fail_reason": message,
        "code_length": code_length,
        "total_execution_time": 0.0,
        "memory_used_mb": None,
    }


async def run_c_sharp_tests(
    task_id: int,
    code_str: str,
    max_code_length: int | None = None,
    max_execution_time_sec: float | None = None,
    max_memory_mb: float | None = None,
    max_variables: int | None = None,
) -> dict:
    cs_service_cfg = get_settings().cs_app

    code_length = _count_code_lines(code_str)
    if max_code_length is not None and code_length > max_code_length:
        return _limit_fail(
            f"Превышена длина кода: {code_length} строк (лимит {max_code_length}).",
            code_length=code_length,
        )

    test_cases = get_test_cases_by_task(task_id)

    if not test_cases:
        return {
            "test_case_number": -1,
            "input_data": "No test cases found.",
            "user_output": "",
            "expected_output": "",
            "status": "Failed",
            "code_length": code_length,
        }

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    test_limits = {}
    if max_execution_time_sec is not None:
        test_limits["MaxExecutionTimeMs"] = int(max_execution_time_sec * 1000)
    if max_memory_mb is not None:
        test_limits["MaxMemoryBytes"] = int(max_memory_mb * 1024 * 1024)

    start_time = time.time()
    response_data = {}
    for index, test_case in enumerate(test_cases):
        data = {
            "StringCode": code_str,
            "Test": {
                "Input": test_case.inp,
                "ExpectedOutput": test_case.out,
                **test_limits,
            }
        }
        response = requests.post(
            f'http://{cs_service_cfg.host}:{str(cs_service_cfg.port)}/CDiazCodeLab/CodeCheck/RunTestsFromString',
            data=json.dumps(data),
            headers=headers
        )

        response_data = response.json()
        result_data = response_data.get('result') or {}

        if not result_data.get('passed') or response_data.get('errorMessage'):
            error_message = (
                result_data.get('errorMessage')
                or response_data.get('errorMessage')
                or ""
            )
            return {
                "test_case_number": index + 1,
                "input_data": (result_data.get('testCase') or {}).get('input', test_case.inp),
                "user_output": result_data.get('actualOutput') or error_message,
                "expected_output": (result_data.get('testCase') or {}).get('expectedOutput', test_case.out),
                "status": "Failed",
                "fail_reason": error_message or None,
                "code_length": code_length,
            }

    end_time = time.time()
    execution_time = round(end_time - start_time, 3)

    if max_execution_time_sec is not None and execution_time > max_execution_time_sec:
        return _limit_fail(
            f"Превышено время выполнения: {execution_time} сек (лимит {max_execution_time_sec}).",
            code_length=code_length,
        )

    return {
        "total_execution_time": execution_time,
        "code_length": code_length,
        "execution_status": "Success",
        "status": "Success"
    }


async def run_tests(
    task_id: int,
    code_str: str,
    max_code_length: int | None = None,
    max_execution_time_sec: float | None = None,
    max_memory_mb: float | None = None,
    max_variables: int | None = None,
) -> dict:
    test_cases = get_test_cases_by_task(task_id)
    if not test_cases:
        return {
            "test_case_number": -1,
            "input_data": "No test cases found.",
            "user_output": "",
            "expected_output": "",
            "status": "Failed",
            "code_length": 0,
        }

    total_execution_time = 0
    code_length = _count_code_lines(code_str)

    if max_code_length is not None and code_length > max_code_length:
        return _limit_fail(
            f"Превышена длина кода: {code_length} строк (лимит {max_code_length}).",
            code_length=code_length,
        )

    if max_variables is not None:
        variables_count = _count_python_variables(code_str)
        if variables_count is not None and variables_count > max_variables:
            return _limit_fail(
                f"Превышено число переменных: {variables_count} (лимит {max_variables}).",
                code_length=code_length,
            )

    per_case_timeout = max_execution_time_sec if max_execution_time_sec is not None else 5

    for index, test_case in enumerate(test_cases):
        input_data = test_case.inp
        expected_output = test_case.out

        code_with_input = f"import sys\ninput = lambda: '{input_data}'\n{code_str}"

        output = io.StringIO()
        start_time = time.time()
        execute_status = True

        def exec_code():
            try:
                with contextlib.redirect_stdout(output):
                    exec(code_with_input)
            except Exception as e:
                nonlocal execute_status
                execute_status = False
                output.write(f"Error executing code: {e}")

        thread = threading.Thread(target=exec_code)
        thread.start()
        thread.join(timeout=per_case_timeout)

        if thread.is_alive():
            output.write("Execution timed out.")
            thread.join()
            return _limit_fail(
                f"Превышено время выполнения: лимит {per_case_timeout} сек.",
                code_length=code_length,
            )

        end_time = time.time()
        execution_time = round(end_time - start_time, 3)
        total_execution_time += execution_time
        result = output.getvalue()

        if max_execution_time_sec is not None and execution_time > max_execution_time_sec:
            return _limit_fail(
                f"Превышено время выполнения: {execution_time} сек (лимит {max_execution_time_sec}).",
                code_length=code_length,
            )

        if result.strip() != expected_output.strip():
            return {
                "test_case_number": index + 1,
                "input_data": input_data,
                "user_output": result.strip(),
                "expected_output": expected_output.strip(),
                "status": "Failed",
                "code_length": code_length,
            }

    return {
        "total_execution_time": round(total_execution_time, 3),
        "code_length": code_length,
        "execution_status": "Success",
        "status": "Success"
    }


# main testing function
async def check_file(
    task_id: int,
    subject_id: int,
    teacher_formula: str,
    input_variables: str,
    student_code: str,
    solution_id: int,
    max_code_length: int | None = None,
    max_execution_time_sec: float | None = None,
    max_memory_mb: float | None = None,
    max_variables: int | None = None,
) -> TestCase:

    limits = {
        "max_code_length": max_code_length,
        "max_execution_time_sec": max_execution_time_sec,
        "max_memory_mb": max_memory_mb,
        "max_variables": max_variables,
    }

    match subject_id:
        case SubjectTypes.Python.value:
            test_result = await run_tests(task_id, student_code, **limits)

        case SubjectTypes.CSharp.value:
            test_result = await run_c_sharp_tests(task_id, student_code, **limits)

        case _:
            raise ValueError("Unsupported subject")

    if test_result.get("status") == "Failed":
        fail_reason = test_result.get("fail_reason")
        code_output = (
            fail_reason
            if fail_reason and test_result.get("test_case_number") in (None, 0, -1)
            else f"Test case {test_result['test_case_number']} failed."
        )
        result = TestCase(
            code_output=code_output,
            input_data=test_result.get("input_data", ""),
            expected_output=test_result.get("expected_output", ""),
            user_output=test_result.get("user_output", ""),
            execution_time=0.0,
            code_length=test_result.get("code_length", 0),
            execution_status="Failed"
        )
    else:
        result = TestCase(
            code_output="All tests passed successfully.",
            input_data="",
            expected_output="",
            user_output="",
            execution_time=test_result["total_execution_time"],
            code_length=test_result.get("code_length", 0),
            execution_status=test_result["status"]
        )

    update_solution_test_result(
        solution_id,
        result.execution_status,
        result.model_dump(mode="json"),
        code_length=result.code_length,
        execution_time=result.execution_time,
        memory_used_mb=result.memory_used_mb,
    )

    return result