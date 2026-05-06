"""
供给侧数据处理服务（V2）

核心修正：
1. 过滤车企品牌站（蔚来/特斯拉/小鹏/理想等），不计入供给
2. 只计算快充枪：同站有快慢充只保留快充枪数，纯慢充站排除
3. 服务费取峰平谷加权值（按司机时段分布）
4. 单枪度数按站点竞争力差异化分配（非平均）
5. 利用率口径 = 单枪日度数 / (功率kW × 24h)
"""
import re
import math
from models.schemas import ChargingStation, Location, SupplyInfo
from services.amap_service import search_all_charging_stations
from services.pricing_service import (
    get_operator_pricing,
    parse_price_from_name,
    calculate_effective_price,
    calculate_gun_health_rate,
    is_car_brand_station,
)


def parse_charging_station(poi: dict, center_lng: float, center_lat: float) -> ChargingStation:
    """
    解析高德POI数据为充电站模型
    """
    loc_str = poi.get("location", "0,0")
    lng, lat = map(float, loc_str.split(","))
    
    name = poi.get("name", "")
    total_guns, fast_guns, slow_guns = _extract_gun_count(poi)
    operator = _extract_operator(name, poi)
    power_kw = _extract_power(poi)
    rating = _extract_rating(poi)
    
    # 好枪率
    gun_health_rate = calculate_gun_health_rate(operator, rating)
    # 好枪数只算快充
    working_guns = max(1, int(fast_guns * gun_health_rate))
    
    # 定价（峰平谷加权）
    parsed_price = parse_price_from_name(name)
    price_info = calculate_effective_price(operator, parsed_price)
    
    return ChargingStation(
        id=poi.get("id", ""),
        name=name,
        location=Location(
            lng=lng,
            lat=lat,
            address=poi.get("address", ""),
            city=poi.get("cityname", ""),
            district=poi.get("adname", ""),
        ),
        operator=operator,
        total_guns=total_guns,
        fast_guns=fast_guns,
        slow_guns=slow_guns,
        power_kw=power_kw,
        distance=float(poi.get("distance", 0)),
        rating=rating,
        working_guns=working_guns,
        gun_health_rate=gun_health_rate,
        service_fee=price_info["weighted_service_fee"],
        activity_service_fee=price_info["weighted_service_fee"],
        electricity_fee=price_info["weighted_electricity"],
        effective_price=price_info["effective_price"],
    )


def _extract_gun_count(poi: dict) -> tuple[int, int, int]:
    """
    从POI信息中提取充电枪数量
    """
    name = poi.get("name", "")
    
    total = 0
    fast = 0
    slow = 0
    
    # 匹配 "X枪" 或 "X个"
    total_match = re.search(r'(\d+)\s*[枪个桩]', name)
    if total_match:
        total = int(total_match.group(1))
    
    # 匹配 "快充X" "慢充X"
    fast_match = re.search(r'快充\s*(\d+)', name)
    slow_match = re.search(r'慢充\s*(\d+)', name)
    
    if fast_match:
        fast = int(fast_match.group(1))
    if slow_match:
        slow = int(slow_match.group(1))
    
    if fast + slow > 0 and total == 0:
        total = fast + slow
    
    # 兜底默认值
    if total == 0:
        total = 8
        fast = 6   # 默认以快充为主
        slow = 2
    elif fast == 0 and slow == 0:
        # 有总数无细分，按7:3估算（当前市场快充为主）
        fast = int(total * 0.7)
        slow = total - fast
    
    return total, fast, slow


def _extract_operator(name: str, poi: dict) -> str:
    """从站名中提取运营商"""
    known_operators = [
        "特来电", "星星充电", "国家电网", "南方电网",
        "小桔充电", "云快充", "万城万充", "依威能源",
        "快电", "新电途", "蔚来", "特斯拉", "小鹏",
        "理想", "比亚迪", "极氪", "问界", "智己",
    ]
    for op in known_operators:
        if op in name:
            return op
    return "其他"


def _extract_power(poi: dict) -> float:
    """提取单枪功率，默认120kW(国内主流快充)"""
    name = poi.get("name", "")
    power_match = re.search(r'(\d+)\s*[kK][wW]', name)
    if power_match:
        return float(power_match.group(1))
    # 2024-2025主流快充桩功率120kW
    return 120.0


def _extract_rating(poi: dict) -> float:
    """从高德biz_ext中提取评分"""
    biz_ext = poi.get("biz_ext", {}) or {}
    rating_str = biz_ext.get("rating", "")
    if rating_str:
        try:
            rating = float(rating_str)
            if 0 < rating <= 5:
                return rating
        except (ValueError, TypeError):
            pass
    return 0.0


def _calculate_station_attractiveness(
    station: ChargingStation,
    avg_price: float,
    max_distance: float
) -> float:
    """
    计算单站吸引力得分（用于差异化分配需求）
    
    影响因子：
    1. 价格因子：价格越低→吸引力越高（权重40%）
    2. 位置因子：距区域中心越近→吸引力越高（权重30%）
    3. 功率因子：功率越高→充电越快→吸引力越高（权重15%）
    4. 评分因子：用户评分越高→体验越好（权重15%）
    
    Returns:
        吸引力得分 (0~1区间的相对值)
    """
    # 价格因子：比均价便宜得分高
    if avg_price > 0 and station.effective_price:
        price_ratio = avg_price / max(station.effective_price, 0.1)
        price_score = min(price_ratio, 2.0) / 2.0  # 归一化到0~1
    else:
        price_score = 0.5
    
    # 位置因子：距离越近得分越高
    if max_distance > 0 and station.distance:
        distance_score = 1.0 - min(station.distance / max_distance, 1.0)
    else:
        distance_score = 0.5
    
    # 功率因子：120kW为基准
    power_score = min((station.power_kw or 120) / 240.0, 1.0)
    
    # 评分因子
    rating_score = (station.rating or 3.0) / 5.0
    
    # 加权综合
    attractiveness = (
        price_score * 0.40
        + distance_score * 0.30
        + power_score * 0.15
        + rating_score * 0.15
    )
    
    return max(attractiveness, 0.05)  # 最低0.05，不能为0


def _distribute_demand_to_stations(
    stations: list[ChargingStation],
    daily_demand_kwh: float
) -> None:
    """
    按站点竞争力差异化分配区域需求到各站
    
    逻辑：
    - 计算每站吸引力得分
    - 吸引力×好枪数 = 该站的需求权重
    - 按权重比例分配总需求
    - 从而得到每站的单枪日度数（各站不同）
    
    利用率口径：
    - 利用率 = 单枪日度数 / (功率kW × 24h)
    - 即"这根枪一天24小时中有多大比例时间在充电"
    """
    if not stations or daily_demand_kwh <= 0:
        return
    
    # 计算辅助指标
    prices = [s.effective_price for s in stations if s.effective_price]
    avg_price = sum(prices) / len(prices) if prices else 1.0
    max_distance = max((s.distance or 0) for s in stations) if stations else 3000
    
    # 计算各站吸引力
    attractiveness_scores = []
    for station in stations:
        score = _calculate_station_attractiveness(station, avg_price, max_distance)
        attractiveness_scores.append(score)
    
    # 计算加权权重 = 吸引力 × 好枪数
    weights = []
    for i, station in enumerate(stations):
        w = attractiveness_scores[i] * station.working_guns
        weights.append(w)
    
    total_weight = sum(weights)
    if total_weight <= 0:
        return
    
    # 按权重分配需求
    for i, station in enumerate(stations):
        station_demand = daily_demand_kwh * (weights[i] / total_weight)
        
        if station.working_guns > 0:
            station.daily_kwh_per_gun = round(station_demand / station.working_guns, 1)
        else:
            station.daily_kwh_per_gun = 0.0
        
        # 利用率 = 单枪日度数 / (功率 × 24小时)
        max_output_per_day = (station.power_kw or 120) * 24
        station.estimated_utilization = round(
            min(station.daily_kwh_per_gun / max_output_per_day, 1.0), 3
        )


async def get_supply_info(
    lng: float, lat: float, radius_km: float = 3.0,
    daily_demand_kwh: float = 0.0
) -> SupplyInfo:
    """
    获取指定区域的充电站供给信息（V2）
    
    关键变化：
    - 过滤车企品牌站
    - 只计快充枪
    - 差异化分配单枪度数
    - 利用率 = 日度数 / (功率×24h)
    """
    radius_m = int(radius_km * 1000)
    
    # 调用高德API获取充电站
    raw_pois = await search_all_charging_stations(lng, lat, radius_m)
    
    # 解析为结构化数据
    all_stations = [parse_charging_station(poi, lng, lat) for poi in raw_pois]
    
    # ===== 过滤 =====
    # 1. 排除车企品牌站
    # 2. 排除纯慢充站（fast_guns == 0）
    stations = []
    for s in all_stations:
        # 排除车企
        if is_car_brand_station(s.operator, s.name):
            continue
        # 排除纯慢充（快充枪为0）
        if s.fast_guns <= 0:
            continue
        stations.append(s)
    
    # 汇总统计（只算快充枪）
    total_guns = sum(s.fast_guns for s in stations)  # 只统计快充
    total_fast = sum(s.fast_guns for s in stations)
    total_slow = sum(s.slow_guns for s in stations)  # 记录但不参与计算
    total_working_guns = sum(s.working_guns for s in stations)
    station_count = len(stations)
    
    # 差异化分配需求到各站
    if daily_demand_kwh > 0:
        _distribute_demand_to_stations(stations, daily_demand_kwh)
    
    # 计算区域平均指标
    avg_utilization = 0.0
    avg_daily_kwh_per_gun = 0.0
    if station_count > 0 and daily_demand_kwh > 0:
        total_daily_kwh = sum(
            s.daily_kwh_per_gun * s.working_guns for s in stations
        )
        if total_working_guns > 0:
            avg_daily_kwh_per_gun = round(total_daily_kwh / total_working_guns, 1)
        
        utils = [s.estimated_utilization for s in stations if s.estimated_utilization > 0]
        if utils:
            avg_utilization = round(sum(utils) / len(utils), 3)
    
    return SupplyInfo(
        center=Location(lng=lng, lat=lat),
        radius_km=radius_km,
        station_count=station_count,
        total_guns=total_guns,  # 只计快充
        total_fast_guns=total_fast,
        total_slow_guns=total_slow,
        total_working_guns=total_working_guns,
        avg_guns_per_station=round(total_guns / max(station_count, 1), 1),
        avg_utilization=avg_utilization,
        avg_daily_kwh_per_gun=avg_daily_kwh_per_gun,
        stations=stations,
    )
