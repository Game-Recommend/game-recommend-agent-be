from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="game-recommend-be")
app.include_router(router)
