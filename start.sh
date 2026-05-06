#!/bin/bash
# 充电站选址评估平台 - 启动脚本

echo "================================"
echo "  充电站选址评估平台 - 启动"
echo "================================"

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 进入后端目录
cd "$(dirname "$0")/backend"

# 创建虚拟环境(如果不存在)
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📦 安装依赖..."
pip install -r requirements.txt -q

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  未找到 .env 文件！"
    echo "请创建 backend/.env 文件并填入你的高德 API Key："
    echo ""
    echo "  AMAP_API_KEY=你的高德Web服务Key"
    echo ""
    echo "获取方式: https://console.amap.com/dev/key/app"
    echo "注意: 需要申请 Web服务 类型的 Key"
    echo ""
    cp .env.example .env
    echo "已创建 .env 模板文件，请编辑后重新启动。"
    exit 1
fi

# 启动后端服务
echo ""
echo "🚀 启动后端服务 (端口 8000)..."
echo "   API 文档: http://localhost:8000/docs"
echo ""
echo "🌐 前端页面请直接用浏览器打开:"
echo "   frontend/index.html"
echo ""
echo "⚠️  注意: 前端 index.html 中的高德JS Key 需要替换为你的 JS API Key"
echo "   (与后端的 Web服务Key 不同，需要在高德控制台单独申请 JS API 类型)"
echo ""
echo "按 Ctrl+C 停止服务"
echo "================================"

uvicorn main:app --reload --host 0.0.0.0 --port 8000
