"""
综合分析 API 路由
"""
from fastapi import APIRouter, Query
from typing import Optional
from services.analysis_service import run_full_evaluation, simulate_user_station
from services.supply_service import get_supply_info
from services.demand_service import estimate_demand
from services.amap_service import geocode_address

router = APIRouter()


@router.get("/evaluate")
async def evaluate_location(
    lng: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    radius: float = Query(3.0, description="评估半径(公里)", ge=0.5, le=50),
):
    """
    对指定位置进行完整的建站可行性评估
    
    返回: 供需分析 + 建站建议 + 经济估算 + 价格影响度
    """
    result = await run_full_evaluation(lng, lat, radius)
    return result


@router.get("/simulate")
async def simulate_station(
    lng: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    radius: float = Query(3.0, description="评估半径(公里)", ge=0.5, le=50),
    guns: int = Query(..., description="用户计划的枪数（车位数）", ge=1, le=100),
    price: Optional[float] = Query(None, description="计划的活动服务费(元/kWh)，不填则自动取区域均价×95%"),
):
    """
    用户自定义模拟：输入枪数（车位数），预估建站后单枪日度数
    """
    import asyncio
    
    # 获取供需数据
    demand = await estimate_demand(lng, lat, radius)
    await asyncio.sleep(1.0)
    supply = await get_supply_info(lng, lat, radius, daily_demand_kwh=demand.daily_charge_demand_kwh)
    
    # 模拟
    result = simulate_user_station(supply, demand, guns, price)
    return result


@router.get("/geocode")
async def geocode(
    address: str = Query(..., description="搜索地址"),
    city: Optional[str] = Query(None, description="城市（可选，提高精度）"),
):
    """
    地址转坐标，前端调用后端高德API进行地理编码
    避免前端直接调用高德JS API受安全域名限制
    """
    result = await geocode_address(address, city)
    return result
