"""
高德地图 API 服务
负责调用高德接口获取充电站POI数据和区域信息
"""
import os
import httpx
from typing import Optional

AMAP_BASE_URL = "https://restapi.amap.com/v3"
AMAP_KEY = os.getenv("AMAP_API_KEY", "")

# 高德POI类型编码: 充电站 = 011100, 加油加气充电站 = 010400
CHARGING_POI_TYPES = "011100|011101|011102|011103"


async def search_charging_stations(
    lng: float,
    lat: float,
    radius_m: int = 3000,
    page: int = 1,
    page_size: int = 50
) -> dict:
    """
    搜索指定坐标周边的充电站
    
    Args:
        lng: 经度
        lat: 纬度
        radius_m: 搜索半径(米), 最大50000
        page: 页码
        page_size: 每页数量, 最大25(高德限制)
    
    Returns:
        高德API原始响应
    """
    params = {
        "key": AMAP_KEY,
        "location": f"{lng},{lat}",
        "types": CHARGING_POI_TYPES,
        "radius": min(radius_m, 50000),
        "offset": min(page_size, 25),
        "page": page,
        "extensions": "all",  # 返回详细信息
        "sortrule": "distance",
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{AMAP_BASE_URL}/place/around", params=params)
        resp.raise_for_status()
        return resp.json()


async def search_all_charging_stations(
    lng: float,
    lat: float,
    radius_m: int = 3000
) -> list[dict]:
    """
    分页获取所有充电站数据
    
    高德单次最多返回25条，需要翻页
    """
    all_pois = []
    page = 1
    
    while True:
        data = await search_charging_stations(lng, lat, radius_m, page=page)
        
        if data.get("status") != "1":
            break
        
        pois = data.get("pois", [])
        if not pois:
            break
        
        all_pois.extend(pois)
        
        # 判断是否还有下一页
        total = int(data.get("count", 0))
        if len(all_pois) >= total:
            break
        
        page += 1
        
        # 安全限制，最多10页
        if page > 10:
            break
    
    return all_pois


async def search_pois_by_type(
    lng: float,
    lat: float,
    poi_types: str,
    radius_m: int = 3000,
) -> list[dict]:
    """
    按类型搜索周边POI（用于需求估算）
    
    常用类型:
    - 住宅区: 120000
    - 商务写字楼: 120200
    - 购物中心: 060100
    - 工厂: 120000
    - 停车场: 150900
    """
    params = {
        "key": AMAP_KEY,
        "location": f"{lng},{lat}",
        "types": poi_types,
        "radius": min(radius_m, 50000),
        "offset": 25,
        "page": 1,
        "extensions": "base",
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{AMAP_BASE_URL}/place/around", params=params)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("status") == "1":
            return data.get("pois", [])
        return []


async def get_district_info(city: str, district: Optional[str] = None) -> dict:
    """
    获取行政区信息（包含人口等数据的辅助查询）
    """
    params = {
        "key": AMAP_KEY,
        "keywords": district or city,
        "subdistrict": 0,
        "extensions": "all",
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{AMAP_BASE_URL}/config/district", params=params)
        resp.raise_for_status()
        return resp.json()


async def geocode_address(address: str, city: Optional[str] = None) -> dict:
    """
    地址转坐标
    """
    params = {
        "key": AMAP_KEY,
        "address": address,
    }
    if city:
        params["city"] = city
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{AMAP_BASE_URL}/geocode/geo", params=params)
        resp.raise_for_status()
        return resp.json()


async def reverse_geocode(lng: float, lat: float) -> dict:
    """
    坐标转地址（逆地理编码）
    用于获取坐标所在的城市、区县等信息
    """
    params = {
        "key": AMAP_KEY,
        "location": f"{lng},{lat}",
        "extensions": "all",
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{AMAP_BASE_URL}/geocode/regeo", params=params)
        resp.raise_for_status()
        return resp.json()
