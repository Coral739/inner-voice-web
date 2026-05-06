"""
充电定价服务

核心原则（来自用户确认）：
- 活动服务费 = 司机真实支付的服务费（挂牌价是虚拟的）
- 服务费分峰平谷三个时段
- 不考虑优惠券逻辑
- 不考虑阶梯计费

定价说明：
- 峰时段：通常 7:00-11:00, 18:00-23:00（高电价+高服务费）
- 平时段：通常 11:00-18:00（中电价+中服务费）
- 谷时段：通常 23:00-7:00（低电价+低服务费，网约车司机主充时段）

日均有效服务费 = 峰×峰权重 + 平×平权重 + 谷×谷权重
网约车司机充电时段分布：谷时50%，平时30%，峰时20%
"""
import re
from typing import Optional


# ===== 网约车司机充电时段权重 =====
# 司机倾向于谷时充电（便宜），实际分布约为：
TIME_WEIGHTS = {
    "peak": 0.20,   # 峰时段充电占比
    "flat": 0.30,   # 平时段充电占比
    "valley": 0.50, # 谷时段充电占比（最多）
}


# ===== 运营商活动服务费定价表（分峰平谷） =====
# 单位：元/kWh
# 取的是活动服务费（真实价），非挂牌虚高价
OPERATOR_PRICING = {
    "特来电": {
        "service_fee_peak": 0.50,     # 峰时活动服务费
        "service_fee_flat": 0.35,     # 平时活动服务费
        "service_fee_valley": 0.20,   # 谷时活动服务费
        "electricity_peak": 1.10,     # 峰时电费
        "electricity_flat": 0.75,     # 平时电费
        "electricity_valley": 0.35,   # 谷时电费
        "gun_health_rate": 0.80,
    },
    "星星充电": {
        "service_fee_peak": 0.45,
        "service_fee_flat": 0.30,
        "service_fee_valley": 0.15,
        "electricity_peak": 1.08,
        "electricity_flat": 0.72,
        "electricity_valley": 0.33,
        "gun_health_rate": 0.82,
    },
    "小桔充电": {
        "service_fee_peak": 0.38,
        "service_fee_flat": 0.25,
        "service_fee_valley": 0.12,
        "electricity_peak": 1.05,
        "electricity_flat": 0.70,
        "electricity_valley": 0.32,
        "gun_health_rate": 0.85,
    },
    "国家电网": {
        "service_fee_peak": 0.50,
        "service_fee_flat": 0.40,
        "service_fee_valley": 0.30,
        "electricity_peak": 1.05,
        "electricity_flat": 0.68,
        "electricity_valley": 0.30,
        "gun_health_rate": 0.90,
    },
    "南方电网": {
        "service_fee_peak": 0.48,
        "service_fee_flat": 0.38,
        "service_fee_valley": 0.28,
        "electricity_peak": 1.00,
        "electricity_flat": 0.65,
        "electricity_valley": 0.28,
        "gun_health_rate": 0.90,
    },
    "云快充": {
        "service_fee_peak": 0.48,
        "service_fee_flat": 0.32,
        "service_fee_valley": 0.18,
        "electricity_peak": 1.08,
        "electricity_flat": 0.73,
        "electricity_valley": 0.34,
        "gun_health_rate": 0.72,
    },
    "快电": {
        "service_fee_peak": 0.42,
        "service_fee_flat": 0.28,
        "service_fee_valley": 0.15,
        "electricity_peak": 1.08,
        "electricity_flat": 0.72,
        "electricity_valley": 0.33,
        "gun_health_rate": 0.78,
    },
    "新电途": {
        "service_fee_peak": 0.45,
        "service_fee_flat": 0.30,
        "service_fee_valley": 0.16,
        "electricity_peak": 1.05,
        "electricity_flat": 0.70,
        "electricity_valley": 0.32,
        "gun_health_rate": 0.78,
    },
    "万城万充": {
        "service_fee_peak": 0.52,
        "service_fee_flat": 0.35,
        "service_fee_valley": 0.22,
        "electricity_peak": 1.10,
        "electricity_flat": 0.75,
        "electricity_valley": 0.35,
        "gun_health_rate": 0.70,
    },
    "依威能源": {
        "service_fee_peak": 0.55,
        "service_fee_flat": 0.38,
        "service_fee_valley": 0.25,
        "electricity_peak": 1.08,
        "electricity_flat": 0.72,
        "electricity_valley": 0.33,
        "gun_health_rate": 0.75,
    },
}

# 默认值（无法识别运营商时）
DEFAULT_PRICING = {
    "service_fee_peak": 0.50,
    "service_fee_flat": 0.35,
    "service_fee_valley": 0.20,
    "electricity_peak": 1.08,
    "electricity_flat": 0.73,
    "electricity_valley": 0.33,
    "gun_health_rate": 0.75,
}

# 车企品牌站列表（需排除）
CAR_BRAND_OPERATORS = {"蔚来", "特斯拉", "小鹏", "理想", "比亚迪", "极氪", "问界", "智己"}


def is_car_brand_station(operator: str, name: str) -> bool:
    """判断是否为车企品牌站"""
    # 运营商直接匹配
    if operator in CAR_BRAND_OPERATORS:
        return True
    # 站名中包含车企品牌关键词
    for brand in CAR_BRAND_OPERATORS:
        if brand in name:
            return True
    return False


def get_operator_pricing(operator: str) -> dict:
    """获取运营商定价信息"""
    return OPERATOR_PRICING.get(operator, DEFAULT_PRICING)


def calculate_weighted_service_fee(operator: str) -> dict:
    """
    计算加权日均服务费（按司机充电时段分布加权）
    
    Returns:
        dict: {
            "service_fee_peak": 峰时活动服务费,
            "service_fee_flat": 平时活动服务费,
            "service_fee_valley": 谷时活动服务费,
            "weighted_service_fee": 加权日均活动服务费,
            "weighted_electricity": 加权日均电费,
            "weighted_total": 加权日均综合单价,
        }
    """
    pricing = get_operator_pricing(operator)
    
    # 加权服务费
    wsf = (
        pricing["service_fee_peak"] * TIME_WEIGHTS["peak"]
        + pricing["service_fee_flat"] * TIME_WEIGHTS["flat"]
        + pricing["service_fee_valley"] * TIME_WEIGHTS["valley"]
    )
    
    # 加权电费
    wef = (
        pricing["electricity_peak"] * TIME_WEIGHTS["peak"]
        + pricing["electricity_flat"] * TIME_WEIGHTS["flat"]
        + pricing["electricity_valley"] * TIME_WEIGHTS["valley"]
    )
    
    return {
        "service_fee_peak": pricing["service_fee_peak"],
        "service_fee_flat": pricing["service_fee_flat"],
        "service_fee_valley": pricing["service_fee_valley"],
        "weighted_service_fee": round(wsf, 3),
        "weighted_electricity": round(wef, 3),
        "weighted_total": round(wsf + wef, 3),
    }


def parse_price_from_name(name: str) -> Optional[float]:
    """从站名中解析价格信息"""
    price_match = re.search(r'(\d+\.?\d*)\s*元[/每]?[度kK]', name)
    if price_match:
        return float(price_match.group(1))
    svc_match = re.search(r'服务费\s*(\d+\.?\d*)', name)
    if svc_match:
        return float(svc_match.group(1))
    return None


def calculate_effective_price(operator: str, parsed_price: Optional[float] = None) -> dict:
    """
    计算场站有效价格（用户真实支付的加权日均价）
    
    Returns:
        dict: {
            "service_fee_peak/flat/valley": 各时段活动服务费,
            "weighted_service_fee": 加权活动服务费,
            "weighted_electricity": 加权电费,
            "effective_price": 加权综合单价（电费+活动服务费）,
        }
    """
    fee_info = calculate_weighted_service_fee(operator)
    
    if parsed_price and parsed_price > 1.0:
        # 站名中解析到的是综合单价，反推服务费
        implied_service_fee = parsed_price - fee_info["weighted_electricity"]
        if implied_service_fee > 0:
            fee_info["weighted_service_fee"] = round(implied_service_fee, 3)
            fee_info["weighted_total"] = round(parsed_price, 3)
    
    return {
        "service_fee_peak": fee_info["service_fee_peak"],
        "service_fee_flat": fee_info["service_fee_flat"],
        "service_fee_valley": fee_info["service_fee_valley"],
        "weighted_service_fee": fee_info["weighted_service_fee"],
        "weighted_electricity": fee_info["weighted_electricity"],
        "effective_price": fee_info["weighted_total"],
    }


def calculate_gun_health_rate(operator: str, rating: Optional[float] = None) -> float:
    """
    计算设备完好率（好枪率）
    
    基础完好率来自运营商行业数据
    高德评分修正：评分越低→故障越多
    修正公式：actual_rate = base_rate × (0.7 + rating/5 × 0.3)
    """
    pricing = get_operator_pricing(operator)
    base_rate = pricing["gun_health_rate"]
    
    if rating is not None and rating > 0:
        modifier = 0.7 + (rating / 5.0) * 0.3
        return round(min(base_rate * modifier, 0.98), 2)
    
    return base_rate
