from typing import Optional

from pydantic import BaseModel

class TestCase(BaseModel):
    code_output: str
    input_data: str
    expected_output: str
    user_output: str
    execution_time: float
    code_length: int
    execution_status: str
    memory_used_mb: Optional[float] = None