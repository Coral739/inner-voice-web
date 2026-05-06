"""
需求侧 API 路由
"""
from fastapi import APIRouter, Query
from services.demand_service import estimate_demand

router = APIRouter()


@router.get("/estimate")
async def get_demand_estimate(
    lng: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    radius: float = Query(3.0, description="评估半径(公里)", ge=0.5, le=50),
):
    """
    估算指定区域的充电需求
    
    基于周边POI密度和类型，结合城市新能源渗透率进行推算
    """
    demand = await estimate_demand(lng, lat, radius)
    return demand
