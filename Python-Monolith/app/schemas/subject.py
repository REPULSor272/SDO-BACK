from pydantic import BaseModel

class SubjectInfo(BaseModel):
    id: int
    name: str
    grade: float | None

class LabStatus(BaseModel):
    id: int
    title: str
    status: str  # "Не выполнено", "Провалено", "Сдано"

class SubjectProgress(BaseModel):
    id: int
    name: str
    completed: int
    total: int
    progress: int  


class StudentStats(BaseModel):
    average_progress: int
    completed_tasks: int
    total_tasks: int
    average_mark: int | None
    subjects: list[SubjectProgress]