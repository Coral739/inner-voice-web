"""
供给侧 API 路由
"""
from fastapi import APIRouter, Query
from services.supply_service import get_supply_info

router = APIRouter()


@router.get("/stations")
async def get_nearby_stations(
    lng: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    radius: float = Query(3.0, description="搜索半径(公里)", ge=0.5, le=50),
):
    """
    获取指定坐标周边的充电站供给数据
    
    返回: 充电站列表、总枪数、快慢充分布等
    """
    supply = await get_supply_info(lng, lat, radius)
    return supply
