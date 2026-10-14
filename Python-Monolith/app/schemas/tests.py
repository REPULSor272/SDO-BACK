from pydantic import BaseModel

class TestCase(BaseModel):
    code_output: str
    input_data: str
    expected_output: str
    user_output: str
    execution_time: float
    code_length: int
    execution_status: str
    input_data: str | None = None
    expected_output: str | None = None
    user_output: str | None = None