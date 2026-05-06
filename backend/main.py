"""
充电站选址评估平台 - 主入口
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 确保从正确路径加载 .env（无论cwd是哪里）
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)  # 必须在其他import之前加载环境变量

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers import supply, demand, analysis

app = FastAPI(
    title="充电站选址评估平台",
    description="帮助充电站老板评估区域供需关系，判断建站可行性",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(supply.router, prefix="/api/supply", tags=["供给侧"])
app.include_router(demand.router, prefix="/api/demand", tags=["需求侧"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["综合分析"])

# 前端静态文件
frontend_dir = Path(__file__).parent / "static"


@app.get("/")
async def serve_frontend():
    return FileResponse(frontend_dir / "index.html")

