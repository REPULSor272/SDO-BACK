import ast
from http.client import HTTPException
from typing import Optional, Union

from fastapi import APIRouter, Header, UploadFile, File, Depends
from fastapi.responses import JSONResponse, Response
from http import HTTPStatus

from app.core.check_auth import check_auth
from app.core.files.files import check_type, decode_python_source
from app.db.subject_methods import get_subject_id_by_task
from app.db.task_methods import add_solution, delete_solution_bd, get_latest_solution, get_task_data, get_user_solutions_by_task, update_solution_hidden
from app.db.user_methods import is_user_enrolled_in_subject
from app.schemas.files import ResponseUpload
from app.schemas.others import Error
from app.schemas.task import TaskInfo, SolutionInfo
from app.schemas.test import ResponseTest
from app.testing_pyfiles.test import check_file
from app.utils.utils import response_with_json
from app.db.student_methods import get_student_labs_file
from app.db.user_task_attempt import add_attempt, get_attempt

router = APIRouter()


# Загрузка решения задачи по task_id
@router.post("/upload/{task_id}", response_model=ResponseUpload, summary="Загрузка кода для лабораторной работы")
async def upload_solution(task_id: int, authorization: str = Header(...), file: UploadFile = File(...)):
    check_data = check_auth(authorization)
    if isinstance(check_data, JSONResponse):
        return check_data
    #Проверка типа файла
    check_result = check_type(file)
    if not check_result[0]:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={"error": check_result[1]}
        )

    file_content = await file.read()

    decode_result = decode_python_source(file_content)
    if not decode_result[0]:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={"error": decode_result[1]}
        )

    code_text = decode_result[1]

    # Добавление решения в БД
    res_add_solution = add_solution(
        code=code_text,
        user_id=check_data["user_id"],
        task_id=task_id,
    )
    # Если решение не добавлено
    if isinstance(res_add_solution, str):
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={"error": res_add_solution}
        )

    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=ResponseUpload(task_id=task_id).model_dump()
    )


# Тестирование файла
@router.post("/test/{task_id}", response_model=ResponseTest, summary="Тестирование лабораторной работы")
async def test_solution(task_id: int, authorization: str = Header(...)):
    check_data = check_auth(authorization)
    if isinstance(check_data, JSONResponse):
        return check_data

    # Проверка, что пользователь принадлежит предмету, к которому относится задача
    subject_id = get_subject_id_by_task(task_id)
    if not subject_id:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"error": "Task not found."}
        )

    user_enrolled = is_user_enrolled_in_subject(check_data['username'], subject_id)
    if not user_enrolled:
        return JSONResponse(
            status_code=HTTPStatus.FORBIDDEN,
            content={"error": "User is not enrolled in the subject."}
        )

    # Получение данных задачи
    task_data = get_task_data(task_id)
    if not task_data:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"error": "Task data not found."}
        )

    # Получение последнего решения пользователя
    latest_solution = get_latest_solution(check_data['user_id'], task_id)
    if not latest_solution:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"error": "Solution not found."}
        )

    #Проверка, на кол-во попыток
    attempst = get_attempt(check_data['user_id'], task_id)
    print(attempst, task_data['max_attempts'])
    if attempst['attempt_used'] >= task_data['max_attempts']:
        return JSONResponse(
                status_code=HTTPStatus.NOT_FOUND,
                content={"error": "Attempst limit"}
            )


    # Выполнение тестирования
    res_check = await check_file(
        task_id,
        subject_id,
        task_data['teacher_formula'],
        task_data['input_variables'],
        latest_solution.code,
        latest_solution.id,
        task_data.get('max_code_length'),
        task_data.get('max_execution_time_sec'),
        task_data.get('max_memory_mb'),
        task_data.get('max_variables'),
    )

    response = ResponseTest(
        status=res_check.execution_status,
        code_output=res_check.code_output,
        input_data=res_check.input_data,
        expected_output=res_check.expected_output,
        user_output=res_check.user_output,
        execution_time=res_check.execution_time,
        code_length=res_check.code_length,
    ).model_dump()

    add_attempt(check_data['user_id'], task_id)

    if res_check.execution_status == "Failed":
        return response_with_json(
            HTTPStatus.BAD_REQUEST,
            response
        )

    return response_with_json(
        HTTPStatus.OK,
        response
    )


# Получение информации о задаче по task_id и информация о том, сдал ли пользователь
# хотя бы одно правильное решение
@router.get("/task/{task_id}", response_model=Union[TaskInfo, Error],
            summary="Получение информации о лабораторной работе и всех ее загруженных решениях")
async def get_task_info(task_id: int, authorization: str = Header(...)):
    check_data = check_auth(authorization)
    if isinstance(check_data, JSONResponse):
        return check_data

    # Получение данных задачи
    task_data = get_task_data(task_id)
    if not task_data:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"error": "Task not found."}
        )

    # Получение решений пользователя для задачи
    user_solutions = get_user_solutions_by_task(check_data['user_id'], task_id)
    # if not user_solutions:
    #     return JSONResponse(
    #         status_code=HTTPStatus.NOT_FOUND,
    #         content=Error(message="No solutions found for this task.").model_dump()
    #     )

    # Проверка, есть ли хотя бы одно успешное решение
    passed_solutions = [sol for sol in user_solutions if sol.status == "Success"]
    status = "Success" if passed_solutions else "Failed"

    # Формирование ответа
    solutions_info = [SolutionInfo(id = sol.id,
                                    code=sol.code, 
                                    status=sol.status or "unknown",
                                    is_hidden=sol.is_hidden,
                                    test_result=sol.test_result).model_dump() for sol in
                      user_solutions]

    attempts_info = get_attempt(check_data['user_id'], task_id)
    
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content=TaskInfo(
            id=task_data['id'],
            name=task_data['name'],
            description=task_data['description'],
            count_subtasks=1,
            status=status,
            attempts_user = attempts_info,
            max_attempts = task_data['max_attempts'],
            max_code_length = task_data.get('max_code_length'),
            max_execution_time_sec = task_data.get('max_execution_time_sec'),
            max_memory_mb = task_data.get('max_memory_mb'),
            max_variables = task_data.get('max_variables'),
            solutions=solutions_info,
        ).model_dump()
    )

@router.get("/task/{task_id}/student/{student_id}")
async def get_task_student(task_id, student_id):
    user_solutions = get_user_solutions_by_task(student_id, task_id)

    solutions_info = [SolutionInfo(
                        id = sol.id,
                        code=sol.code, 
                        status=sol.status or "unknown",
                        is_hidden=sol.is_hidden,
                        test_result=sol.test_result).model_dump() for sol in  user_solutions]
    
    attempts_info = get_attempt(student_id, task_id)

    return JSONResponse(
            status_code=HTTPStatus.OK,
            content=solutions_info 
        )


@router.post("/task/solution/{solution_id}/hide", summary="Скрытие конкретного решения")
async def hide_solution(solution_id: int, authorization: str = Header(...)):
    auth_data = check_auth(authorization)
    if isinstance(auth_data, JSONResponse):
        return auth_data
    if update_solution_hidden(auth_data['user_id'], solution_id):
        return {"message": "Solution hidden successfully"}
    else:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"detail": "Solution not found or access denied"}
        )


@router.delete("/task/solution/{solution_id}", summary="Удаление конкретного решения")
async def delete_solution(solution_id: int, authorization: str = Header(...)):
    auth_data = check_auth(authorization)

    if isinstance(auth_data, JSONResponse):
        return auth_data

    user_role = auth_data.get("roleType")
    user_id = auth_data.get("user_id")  # Уточнить название поля

    if user_role not in ("teacher", "student"):
        return JSONResponse(
            status_code=HTTPStatus.FORBIDDEN,
            content={"detail": "Access denied"}
        )

    if delete_solution_bd(solution_id, user_id, user_role):
        return {"message": "Решение удалено"}

    return JSONResponse(
        status_code=HTTPStatus.NOT_FOUND,
        content={"detail": "Solution not found or access denied"})

@router.get("/task/{task_id}/download/{student_id}", summary="Скачать последнее решение студента")
async def download_student_file(task_id: int, student_id: int, authorization: Optional[str] = Header(None)):

    if not authorization:
        return JSONResponse(
            status_code=HTTPStatus.UNAUTHORIZED,
            content={"detail": "Authorization header missing"}
        )

    check_data = check_auth(authorization)
    if isinstance(check_data, JSONResponse):
        return check_data
    
    # 2. Достаем код через нашу функцию
    code_text = get_student_labs_file(student_id=student_id, task_id=task_id)
    
    if not code_text:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"detail": "Solution not found"}
        )

    # 3. Отдаем как файл для скачивания
    filename = f"lab_{task_id}_student_{student_id}.py"
    
    return Response(
        content=code_text,
        media_type="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )