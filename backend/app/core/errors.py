"""RFC 9457 Problem Details for HTTP APIs (Contract 2.2 §4)."""
from typing import Any, Dict, List, Optional
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ProblemDetails(BaseModel):
    """RFC 9457 compliant problem response payload."""
    type: str = Field(default="about:blank", description="URI reference identifying problem type")
    title: str = Field(..., description="Short, human-readable summary of problem")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Human-readable explanation specific to this occurrence")
    instance: Optional[str] = Field(default=None, description="URI reference identifying specific occurrence")
    code: str = Field(..., description="Canonical FreightOps error code (ERR-xxx)")
    trace_id: Optional[str] = Field(default=None, description="Distributed tracing identifier")
    errors: Optional[List[Dict[str, Any]]] = Field(default=None, description="Field-level validation error details")


class FreightOpsHTTPException(Exception):
    """Base application exception returning RFC 9457 problem details."""
    def __init__(
        self,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        errors: Optional[List[Dict[str, Any]]] = None,
        instance: Optional[str] = None,
    ):
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors
        self.instance = instance
        super().__init__(detail)


async def freightops_exception_handler(request: Request, exc: FreightOpsHTTPException) -> JSONResponse:
    """FastAPI exception handler formatting FreightOpsHTTPException as application/problem+json."""
    trace_id = request.headers.get("X-Trace-ID") or getattr(request.state, "trace_id", "trace-unknown")
    problem = ProblemDetails(
        type=f"https://freightops.invalid/problems/{exc.code.lower()}",
        title=exc.title,
        status=exc.status_code,
        detail=exc.detail,
        instance=exc.instance or str(request.url.path),
        code=exc.code,
        trace_id=trace_id,
        errors=exc.errors,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump(exclude_none=True),
        headers={"Content-Type": "application/problem+json"},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI exception handler formatting schema validation errors as RFC 9457 application/problem+json."""
    trace_id = request.headers.get("X-Trace-ID") or getattr(request.state, "trace_id", "trace-unknown")
    field_errors = []
    for err in exc.errors():
        field_path = ".".join(str(loc) for loc in err.get("loc", []))
        field_errors.append({
            "field": field_path,
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        })
    problem = ProblemDetails(
        type="https://freightops.invalid/problems/err-001",
        title="Validation Failed",
        status=422,
        detail="One or more request fields failed schema validation.",
        instance=str(request.url.path),
        code="ERR-001",
        trace_id=trace_id,
        errors=field_errors,
    )
    return JSONResponse(
        status_code=422,
        content=problem.model_dump(exclude_none=True),
        headers={"Content-Type": "application/problem+json"},
    )
