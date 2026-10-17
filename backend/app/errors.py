from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def register_error_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {
                    "code": (
                        "NOT_FOUND"
                        if exc.status_code == 404
                        else f"HTTP_{exc.status_code}"
                    ),
                    "message": str(exc.detail),
                    "details": {},
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request,
        exc: RequestValidationError,
    ):
        issues = [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Check the request parameters.",
                    "details": {"issues": issues},
                }
            },
        )