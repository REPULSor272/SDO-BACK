from typing import Optional

from pydantic import BaseModel

class SolutionInfo(BaseModel):
    id: int
    code: str = ""
    status: str = ""
    is_hidden: bool
    test_result: dict | None = None

class TaskInfo(BaseModel):
    id: int = 0
    name: str = ""
    description: str = ""
    count_subtasks: int = 0
    status: str = ""
    attempts_user: dict
    max_attempts: int
    max_code_length: Optional[int] = None
    max_execution_time_sec: Optional[float] = None
    max_memory_mb: Optional[float] = None
    max_variables: Optional[int] = None
    solutions: list[SolutionInfo] = []

class Task(BaseModel):
    id: int
    name: str
    description: str
    status: str = "Не выполнено"

class StudentTaskResult(BaseModel):
    user_id: int
    username: str
    group: str
    score: Optional[int] = None
    isSubmitted: bool

class MarkUpdateSchema(BaseModel):
    mark: int