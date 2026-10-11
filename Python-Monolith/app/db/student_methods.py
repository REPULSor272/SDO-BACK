from typing import Type, Union
from app.db.db import Group, GroupSubject, Session, Solution, Subject, User, Task
from app.db.group_methods import get_groups_by_faculty
from app.db.task_methods import is_task_completed
from app.schemas.subject import LabStatus
from app.schemas.task import SolutionInfo, TaskInfo
from app.schemas.users import UserInfo
from sqlalchemy import func, case


def reg_user_in_subject(user_id, subject_identifier):
    with Session() as session:
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                raise ValueError(f"User with ID {user_id} not found.")

            if isinstance(subject_identifier, int):
                subject = session.query(Subject).filter_by(id=subject_identifier).first()
            else:
                subject = session.query(Subject).filter_by(name=subject_identifier).first()

            if not subject:
                raise ValueError(f"Subject with identifier '{subject_identifier}' not found.")

            if subject in user.subjects:
                raise ValueError(f"User with ID {user_id} is already enrolled in the subject '{subject.name}'.")

            user.subjects.append(subject)
            session.commit()

        except Exception as e:
            session.rollback()
            print(f"Error enrolling user {user_id} in subject {subject_identifier}: {e}")
            raise


def get_users_by_group(group_id) -> list[UserInfo] | str:
    with Session() as session:
        users = session.query(User).filter_by(studyGroup=group_id).all()

        if not users:
            return f"No users found for group with ID {group_id}."

        users_info: list[UserInfo] = []
        for user in users:
            user_info = UserInfo(
                id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                middle_name=user.middle_name,
                studyGroup=user.group_rel.name,
            )
            users_info.append(user_info)

        return users_info


def get_student_tasks_with_status(user_id: int) -> list[dict]:
    with Session() as session:
        user_group = session.query(User).filter_by(id=user_id).first()
        student_subjects = session.query(GroupSubject.subject_id) \
            .filter(GroupSubject.group_id == user_group.group_rel.id) \
            .all()

        if not student_subjects:
            return []

        subject_ids = [subj.subject_id for subj in student_subjects]

        tasks = session.query(Task) \
            .filter(Task.Subject_id.in_(subject_ids), Task.status == 'published') \
            .order_by(Task.id) \
            .all()

        result = []
        for task in tasks:
            completed = is_task_completed(session, user_id, task.id)

            latest_solution = session.query(Solution) \
                .filter_by(User_id=user_id, Task_id=task.id) \
                .order_by(Solution.id.desc()) \
                .first()

            if latest_solution is None:
                status = "not_started"
            elif latest_solution.status == "Success":
                status = "success"
            elif latest_solution.status == "Failed":
                status = "failed"
            else:
                status = "not_started"

            result.append({
                "id": task.id,
                "name": task.name,
                "completed": completed,
                "status": status,
                "subject_id": task.Subject_id,
                "subject_name": task.subject.name if task.subject else "Не указано",
            })

        return result


def get_student_labs_by_subject(student_id: int, subject_id: int) -> list[LabStatus]:
    with Session() as session:
        labs_status = (
            session.query(
                Task.id.label("task_id"),
                Task.name.label("task_name"),
                func.coalesce(
                    func.max(
                        case(
                            (Solution.status == "Success", "Сдано"),
                            (Solution.status == "Failed", "Провалено"),
                            else_="Не выполнено"
                        )
                    ), "Не выполнено"
                ).label("status")
            )
            .outerjoin(
                Solution,
                (Task.id == Solution.Task_id) & (Solution.User_id == student_id)
            )
            .filter(Task.Subject_id == subject_id)
            .group_by(Task.id, Task.name)
            .all()
        )

        result = [
            LabStatus(
                id=row.task_id,
                title=row.task_name,
                status=row.status
            )
            for row in labs_status
        ]

        return result


def get_student_labs(student_id: int, lab_id: int) -> TaskInfo | str:
    with Session() as session:
        task = session.query(Task).filter_by(id=lab_id).first()
        if not task:
            return f"Лабораторная работа с ID {lab_id} не найдена"

        status_query = (
            session.query(
                func.coalesce(
                    func.max(
                        case(
                            (Solution.status == "Success", "Сдано"),
                            (Solution.status == "Failed", "Провалено"),
                            else_="Не выполнено"
                        )
                    ), "Не выполнено"
                ).label("status")
            )
            .filter(Solution.User_id == student_id)
            .filter(Solution.Task_id == lab_id)
        ).scalar()

        solutions = (
            session.query(Solution)
            .filter(Solution.User_id == student_id)
            .filter(Solution.Task_id == lab_id)
            .all()
        )

        if not solutions:
            return f"No solutions found for student with ID {student_id} and task with ID {lab_id}."
        print([(solution.code, solution.status) for solution in solutions])

        solutions_list = [
            SolutionInfo(
                code=solution.code,
                status=solution.status if solution.status else "Не выполнено",
            )
            for solution in solutions
        ]

        response = TaskInfo(
            id=task.id,
            name=task.name,
            description=task.description,
            count_subtasks=1,
            status=status_query,
            solutions=solutions_list
        )

        return response


def get_student_labs_file(student_id: int, task_id: int) -> str | None:
    with Session() as session:
        latest_solution = (
            session.query(Solution)
            .filter(
                Solution.Task_id == task_id,
                Solution.User_id == student_id,
                Solution.is_hidden == False
            )
            .order_by(Solution.id.desc())
            .first()
        )

        if not latest_solution:
            return None

        return latest_solution.code


def get_users_by_faculty(faculty_id: int) -> Union[list[UserInfo], str]:
    with Session() as session:
        groups = get_groups_by_faculty(faculty_id)

        if not groups:
            return f"No groups found for faculty with ID {faculty_id}."

        users = []
        for group in groups:
            group_users = session.query(User).filter_by(studyGroup=group.id).all()
            for user in group_users:
                user_info = UserInfo(
                    id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    middle_name=user.middle_name,
                    studyGroup=user.group_rel.name,
                )
                users.append(user_info)

        if not users:
            return f"No users found for faculty with ID {faculty_id}."

        return users