from pydantic import BaseModel

class ResponseTest(BaseModel):
    status: str
    code_output: str
    input_data: str | None = None
    expected_output: str | None = None
    user_output: str | None = None
    execution_time: float
    code_length: int
