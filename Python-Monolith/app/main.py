from uvicorn import run
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.routers import router as app_router
from app.middleware.auth import AuthMiddleware

settings = get_settings()

app = FastAPI(title="SDO API", description="API for SDO", version="0.1.0")




app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(app_router)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


def main():
    run(app, host=settings.app.host, port=settings.app.port)


if __name__ == "__main__":
    main()