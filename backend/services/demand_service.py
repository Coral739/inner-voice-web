"""
需求侧估算服务

核心逻辑:
1. 通过周边POI分析确定区域类型(住宅/商业/工业/混合)
2. 通过区域类型 + POI密度估算人口/车辆密度
3. 结合新能源渗透率计算充电需求

参数来源(2024-2025年行业数据):
- 全国千人汽车保有量: 约230辆
- 新能源渗透率(保有量口径): 约8-10%(一线城市15-25%)
- 日均充电比例: 约20-30%的新能源车每天需要充电
- 单次充电量: 平均30-40kWh
- 高峰时段: 约为日均的2-3倍
"""
from models.schemas import DemandEstimate, Location
from services.amap_service import search_pois_by_type, reverse_geocode


# ===== 城市分级新能源渗透率 =====
# 基于保有量口径的新能源车占比
CITY_EV_PENETRATION = {
    "tier1": 0.20,  # 一线城市: 北上广深
    "tier2": 0.12,  # 新一线/二线
    "tier3": 0.08,  # 三线
    "tier4": 0.05,  # 四五线及以下
}

TIER1_CITIES = {"北京", "上海", "广州", "深圳"}
TIER2_CITIES = {
    "成都", "杭州", "武汉", "南京", "重庆", "苏州", "西安",
    "长沙", "郑州", "东莞", "青岛", "合肥", "佛山", "宁波",
    "昆明", "沈阳", "天津", "厦门", "无锡", "济南", "大连",
    "福州", "温州", "珠海",
}

# ===== POI类型编码 =====
POI_RESIDENTIAL = "120000"     # 住宅区
POI_OFFICE = "120200"          # 商务写字楼
POI_SHOPPING = "060100|060400" # 商场/超市
POI_INDUSTRIAL = "120301"      # 产业园区/工厂
POI_PARKING = "150900"         # 停车场
POI_TRANSPORT = "150100|150200" # 公交站/地铁站


# ===== 区域类型充电特征 =====
AREA_TYPE_PARAMS = {
    "residential": {
        "label": "居民区",
        "pop_density_per_poi": 2000,  # 每个住宅小区POI对应约2000人
        "car_ownership_ratio": 0.35,  # 户均车辆比
        "daily_charge_ratio": 0.20,   # 日充电比例(居民区偏低，有家充)
        "avg_charge_kwh": 35,         # 单次充电量
        "peak_factor": 2.0,           # 高峰/均值比
        "preferred_fast_ratio": 0.4,  # 建议快充占比
    },
    "commercial": {
        "label": "商业/办公区",
        "pop_density_per_poi": 3000,
        "car_ownership_ratio": 0.45,
        "daily_charge_ratio": 0.30,   # 商业区充电需求高(无家充)
        "avg_charge_kwh": 25,         # 单次充电量偏低(快充补电)
        "peak_factor": 2.5,
        "preferred_fast_ratio": 0.7,  # 快充需求高
    },
    "industrial": {
        "label": "工业/物流区",
        "pop_density_per_poi": 1000,
        "car_ownership_ratio": 0.50,  # 物流车多
        "daily_charge_ratio": 0.40,   # 运营车辆每天都要充
        "avg_charge_kwh": 50,         # 物流车电池大
        "peak_factor": 1.8,
        "preferred_fast_ratio": 0.8,
    },
    "mixed": {
        "label": "混合区域",
        "pop_density_per_poi": 2000,
        "car_ownership_ratio": 0.40,
        "daily_charge_ratio": 0.25,
        "avg_charge_kwh": 30,
        "peak_factor": 2.2,
        "preferred_fast_ratio": 0.6,
    },
}


def _get_city_tier(city: str) -> str:
    """判断城市等级"""
    if any(c in city for c in TIER1_CITIES):
        return "tier1"
    if any(c in city for c in TIER2_CITIES):
        return "tier2"
    return "tier3"


def _determine_area_type(poi_counts: dict) -> str:
    """
    根据各类型POI数量判断区域类型
    """
    residential = poi_counts.get("residential", 0)
    commercial = poi_counts.get("commercial", 0)
    industrial = poi_counts.get("industrial", 0)
    
    total = residential + commercial + industrial
    if total == 0:
        return "mixed"
    
    # 哪种类型占比超过50%就归为该类型
    if residential / max(total, 1) > 0.5:
        return "residential"
    if commercial / max(total, 1) > 0.5:
        return "commercial"
    if industrial / max(total, 1) > 0.5:
        return "industrial"
    
    return "mixed"


async def estimate_demand(lng: float, lat: float, radius_km: float = 3.0) -> DemandEstimate:
    """
    估算指定区域的充电需求
    
    方法论:
    1. 用高德POI搜索获取周边住宅/商业/工业POI数量
    2. 根据POI类型和密度推算区域人口/车辆
    3. 结合城市新能源渗透率计算充电需求
    """
    radius_m = int(radius_km * 1000)
    
    # 1. 获取区域信息(城市、区县)
    regeo = await reverse_geocode(lng, lat)
    regeo_component = regeo.get("regeocode", {}).get("addressComponent", {})
    city = regeo_component.get("city", "") or regeo_component.get("province", "")
    district = regeo_component.get("district", "")
    
    # 2. 搜索各类型POI
    residential_pois = await search_pois_by_type(lng, lat, POI_RESIDENTIAL, radius_m)
    commercial_pois = await search_pois_by_type(lng, lat, f"{POI_OFFICE}|{POI_SHOPPING}", radius_m)
    industrial_pois = await search_pois_by_type(lng, lat, POI_INDUSTRIAL, radius_m)
    parking_pois = await search_pois_by_type(lng, lat, POI_PARKING, radius_m)
    
    poi_counts = {
        "residential": len(residential_pois),
        "commercial": len(commercial_pois),
        "industrial": len(industrial_pois),
        "parking": len(parking_pois),
    }
    
    # 3. 判断区域类型
    area_type = _determine_area_type(poi_counts)
    params = AREA_TYPE_PARAMS[area_type]
    
    # 4. 估算人口
    total_pois = sum(poi_counts.values()) - poi_counts["parking"]
    population_estimate = max(total_pois * params["pop_density_per_poi"], 5000)
    
    # 5. 计算POI密度评分 (0-1)
    # 以3km半径为基准，20个POI算中等密度
    area_sq_km = 3.14159 * radius_km ** 2
    poi_per_sq_km = total_pois / max(area_sq_km, 0.1)
    poi_density_score = min(poi_per_sq_km / 30.0, 1.0)  # 30个/km²为满分
    
    # 6. 估算新能源车数量
    city_tier = _get_city_tier(city if isinstance(city, str) else "")
    ev_penetration = CITY_EV_PENETRATION.get(city_tier, 0.08)
    
    # 汽车保有量 = 人口 × 千人保有量 / 1000
    car_count = int(population_estimate * 230 / 1000 * params["car_ownership_ratio"])
    ev_count = int(car_count * ev_penetration)
    
    # 7. 计算日充电需求
    daily_charge_vehicles = int(ev_count * params["daily_charge_ratio"])
    daily_charge_demand_kwh = daily_charge_vehicles * params["avg_charge_kwh"]
    
    # 8. 计算高峰时段并发需求(转换为需要的枪数)
    # 假设高峰时段4小时内集中了60%的日充电量
    peak_hourly_kwh = daily_charge_demand_kwh * 0.6 / 4
    avg_gun_power = 60  # kW
    peak_concurrent_guns = int(peak_hourly_kwh / avg_gun_power) + 1
    
    return DemandEstimate(
        center=Location(lng=lng, lat=lat, city=city, district=district),
        radius_km=radius_km,
        population_estimate=population_estimate,
        area_type=area_type,
        poi_density_score=round(poi_density_score, 2),
        ev_count_estimate=ev_count,
        daily_charge_demand_kwh=round(daily_charge_demand_kwh, 1),
        peak_concurrent_demand=peak_concurrent_guns,
    )
