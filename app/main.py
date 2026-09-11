from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="game-recommend-app")
app.include_router(router)
