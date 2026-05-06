"""
数据模型定义
"""
from pydantic import BaseModel
from typing import Optional


class Location(BaseModel):
    """位置坐标"""
    lng: float  # 经度
    lat: float  # 纬度
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None


class ChargingStation(BaseModel):
    """充电站信息"""
    id: str
    name: str
    location: Location
    operator: Optional[str] = None  # 运营商
    total_guns: int = 0  # 总枪数
    fast_guns: int = 0  # 快充枪数
    slow_guns: int = 0  # 慢充枪数
    power_kw: Optional[float] = None  # 单枪功率(kW)
    distance: Optional[float] = None  # 距目标点距离(米)
    # 新增：运营质量和定价字段
    rating: Optional[float] = None  # 用户评分(高德)
    working_guns: int = 0  # 好枪数（仅快充，完好率修正后）
    gun_health_rate: float = 0.8  # 设备完好率
    service_fee: Optional[float] = None  # 加权日均活动服务费(元/kWh)
    activity_service_fee: Optional[float] = None  # 同上（加权峰平谷）
    electricity_fee: Optional[float] = None  # 加权日均电费(元/kWh)
    effective_price: Optional[float] = None  # 加权综合单价(电费+活动服务费)
    estimated_utilization: float = 0.0  # 利用率 = 日度数/(功率×24h)
    daily_kwh_per_gun: float = 0.0  # 单枪日均度数（差异化，各站不同）


class SupplyInfo(BaseModel):
    """供给侧汇总"""
    center: Location
    radius_km: float
    station_count: int
    total_guns: int
    total_fast_guns: int
    total_slow_guns: int
    total_working_guns: int = 0  # 区域好枪总数
    avg_guns_per_station: float
    avg_utilization: float = 0.0  # 区域平均利用率
    avg_daily_kwh_per_gun: float = 0.0  # 区域单枪平均日度数
    stations: list[ChargingStation]


class PriceAnalysis(BaseModel):
    """价格影响度分析"""
    avg_effective_price: float = 0.0  # 区域平均有效价格
    price_std: float = 0.0  # 价格标准差
    price_cv: float = 0.0  # 离散系数(标准差/均值)
    price_influence_score: float = 0.0  # 价格影响度(0~1)
    price_influence_level: str = "low"  # low/medium/high
    lowest_price: float = 0.0  # 区域最低价
    highest_price: float = 0.0  # 区域最高价
    suggested_pricing: Optional[float] = None  # 建议新站定价
    pricing_advice: str = ""  # 定价建议文字


class DemandEstimate(BaseModel):
    """需求侧估算"""
    center: Location
    radius_km: float
    # 区域属性
    population_estimate: int  # 估算人口
    area_type: str  # 区域类型: residential/commercial/industrial/mixed
    poi_density_score: float  # POI密度评分 0-1
    # 充电需求估算
    ev_count_estimate: int  # 估算新能源车数
    daily_charge_demand_kwh: float  # 日充电需求(kWh)
    peak_concurrent_demand: int  # 高峰时段并发充电需求(枪数)


class EvaluationResult(BaseModel):
    """评估结果"""
    supply: SupplyInfo
    demand: DemandEstimate
    # 核心指标
    supply_demand_ratio: float  # 供需比 (>1 供大于求, <1 供不应求)
    gap_guns: int  # 缺口枪数(负数表示过剩)
    # 建站建议
    recommendation: str  # "strong_recommend" / "recommend" / "cautious" / "not_recommend"
    suggested_guns: int  # 建议枪数
    suggested_fast_ratio: float  # 建议快充比例
    estimated_daily_revenue: float  # 预估日收入(元)
    estimated_payback_months: int  # 预估回本周期(月)
    reasoning: str  # 分析说明
    # 新增：价格影响度
    price_analysis: Optional[PriceAnalysis] = None
