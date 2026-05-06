"""
综合分析服务（升级版）

核心升级：
1. 用好枪数（而非总枪数）计算供给能力
2. 计算单枪日度数和利用率
3. 新增价格影响度模块
4. 用活动服务费（真实价）做价格分析
"""
import statistics
from models.schemas import (
    SupplyInfo, DemandEstimate, EvaluationResult, PriceAnalysis
)
from services.supply_service import get_supply_info
from services.demand_service import estimate_demand, AREA_TYPE_PARAMS


# ===== 经营参数(可配置) =====
DEFAULT_SERVICE_FEE = 0.28       # 加权日均活动服务费(元/kWh)
DEFAULT_ELECTRICITY_SPREAD = 0.20 # 电费价差(元/kWh)，峰谷套利空间
TARGET_UTILIZATION = 0.25        # 目标利用率(25%是盈利线，口径:日度数/功率×24h)
MAX_UTILIZATION = 0.50           # 利用率上限(口径:日度数/功率×24h，超过说明供不应求)
INVESTMENT_PER_GUN_FAST = 150000 # 快充单枪投资(元)
AVG_GUN_POWER_KW = 120          # 平均快充枪功率(kW)，2024-2025主流


def calculate_price_analysis(supply: SupplyInfo) -> PriceAnalysis:
    """
    价格影响度计算
    
    逻辑：
    1. 收集区域内各站的活动服务费（真实价）
    2. 计算均值和标准差
    3. 离散系数(CV) = std / mean → 衡量价格竞争激烈度
    4. CV → 价格影响度得分(0~1)
    
    价格影响度的含义：
    - 低(0~0.3)：区域定价统一，用户选站主要看位置
    - 中(0.3~0.7)：有价格差异，用户会比价
    - 高(0.7~1.0)：价格战激烈，低价站虹吸效应明显
    """
    # 收集各站有效价格（活动服务费）
    prices = []
    for station in supply.stations:
        if station.activity_service_fee and station.activity_service_fee > 0:
            prices.append(station.activity_service_fee)
    
    if len(prices) < 2:
        return PriceAnalysis(
            avg_effective_price=prices[0] if prices else 0.35,
            price_std=0.0,
            price_cv=0.0,
            price_influence_score=0.0,
            price_influence_level="low",
            lowest_price=prices[0] if prices else 0.0,
            highest_price=prices[0] if prices else 0.0,
            suggested_pricing=0.35,
            pricing_advice="区域内站点不足，定价参考行业均值即可",
        )
    
    avg_price = statistics.mean(prices)
    price_std = statistics.stdev(prices)
    
    # 离散系数
    cv = price_std / avg_price if avg_price > 0 else 0.0
    
    # 价格影响度：CV / 0.3 映射到 0~1
    price_influence_score = round(min(cv / 0.3, 1.0), 2)
    
    # 影响等级
    if price_influence_score < 0.3:
        level = "low"
    elif price_influence_score < 0.7:
        level = "medium"
    else:
        level = "high"
    
    lowest = min(prices)
    highest = max(prices)
    
    # 定价建议
    suggested_pricing, pricing_advice = _generate_pricing_advice(
        avg_price, price_influence_score, level, lowest, highest
    )
    
    return PriceAnalysis(
        avg_effective_price=round(avg_price, 3),
        price_std=round(price_std, 3),
        price_cv=round(cv, 3),
        price_influence_score=price_influence_score,
        price_influence_level=level,
        lowest_price=round(lowest, 3),
        highest_price=round(highest, 3),
        suggested_pricing=round(suggested_pricing, 2),
        pricing_advice=pricing_advice,
    )


def _generate_pricing_advice(
    avg_price: float,
    influence_score: float,
    level: str,
    lowest: float,
    highest: float,
) -> tuple[float, str]:
    """生成定价建议"""
    
    if level == "low":
        suggested = avg_price
        advice = (
            f"区域活动服务费集中在{lowest:.2f}~{highest:.2f}元/kWh，"
            f"定价统一度高，用户选站主要看位置和距离。"
            f"新站可参照区域均价{avg_price:.2f}元定价，无需价格战。"
        )
    elif level == "medium":
        suggested = round(avg_price * 0.95, 2)
        advice = (
            f"区域活动服务费{lowest:.2f}~{highest:.2f}元/kWh，"
            f"存在一定价差，用户会进行比价。"
            f"建议定价略低于均价，在{suggested:.2f}元/kWh左右，"
            f"通过微幅价格优势+好的位置获客。"
        )
    else:
        suggested = round(lowest + (avg_price - lowest) * 0.3, 2)
        advice = (
            f"区域价格战激烈，活动服务费{lowest:.2f}~{highest:.2f}元/kWh，"
            f"价差达{(highest-lowest):.2f}元。低价站虹吸效应明显。"
            f"新站需定价在{suggested:.2f}元/kWh以下才能有效获客，"
            f"否则利用率会显著低于区域平均水平。注意：压价过低会影响回本周期。"
        )
    
    return suggested, advice


def calculate_evaluation(supply: SupplyInfo, demand: DemandEstimate) -> EvaluationResult:
    """
    核心评估算法（V3）
    
    关键改动：
    1. 不再给"不建议建站"的结论，而是客观描述现状
    2. 以单枪日度数120kWh为盈利下限，推算可新增枪数
    3. 新增用户自定义枪数模拟接口
    """
    area_params = AREA_TYPE_PARAMS.get(demand.area_type, AREA_TYPE_PARAMS["mixed"])
    
    # ===== 1. 供给能力计算（基于好枪数，只算快充） =====
    existing_supply_capacity_kwh = (
        supply.total_working_guns * AVG_GUN_POWER_KW * 24 * MAX_UTILIZATION
    )
    
    # ===== 2. 供需比（基于好枪） =====
    if demand.daily_charge_demand_kwh > 0:
        supply_demand_ratio = round(
            existing_supply_capacity_kwh / demand.daily_charge_demand_kwh, 2
        )
    else:
        supply_demand_ratio = 99.0
    
    # ===== 3. 核心指标：当前单枪度数和可新增枪数 =====
    # 当前区域平均单枪日度数
    current_kwh_per_gun = 0.0
    if supply.total_working_guns > 0:
        current_kwh_per_gun = demand.daily_charge_demand_kwh / supply.total_working_guns
    
    # 以120度/枪/天为盈利下限，倒推区域最多能容纳多少根枪
    MIN_VIABLE_KWH_PER_GUN = 120.0
    max_viable_guns = int(demand.daily_charge_demand_kwh / MIN_VIABLE_KWH_PER_GUN)
    
    # 可新增枪数 = 最大可容纳枪数 - 现有好枪数
    gap_guns = max(0, max_viable_guns - supply.total_working_guns)
    
    # ===== 4. 价格影响度分析 =====
    price_analysis = calculate_price_analysis(supply)
    
    # ===== 5. 建站规模建议 =====
    # 不再一棒子拍死，而是基于120度下限给建议
    if gap_guns >= 8:
        recommendation = "viable"
        # 建议吃掉30-50%的空间
        suggested_guns = max(4, min(int(gap_guns * 0.4), gap_guns))
    elif gap_guns >= 4:
        recommendation = "tight"
        suggested_guns = max(4, gap_guns)
    else:
        recommendation = "saturated"
        suggested_guns = 0
    
    # 枪数上限约束
    if suggested_guns > 0:
        suggested_guns = min(suggested_guns, 40)  # 单站不超过40枪
    
    suggested_fast_ratio = 1.0  # 全部快充
    
    # ===== 6. 经济估算 =====
    if suggested_guns > 0:
        # 新站加入后的单枪度数（模拟）
        new_total_guns = supply.total_working_guns + suggested_guns
        new_kwh_per_gun = demand.daily_charge_demand_kwh / new_total_guns if new_total_guns > 0 else 0
        
        revenue_per_kwh = DEFAULT_SERVICE_FEE + DEFAULT_ELECTRICITY_SPREAD
        daily_revenue = suggested_guns * new_kwh_per_gun * revenue_per_kwh
        
        total_investment = suggested_guns * INVESTMENT_PER_GUN_FAST
        monthly_net_revenue = daily_revenue * 30 * 0.7
        payback_months = int(total_investment / max(monthly_net_revenue, 1))
    else:
        new_kwh_per_gun = current_kwh_per_gun
        daily_revenue = 0
        payback_months = 0
    
    # ===== 7. 生成说明文字 =====
    reasoning = _generate_reasoning(
        supply, demand, supply_demand_ratio, current_kwh_per_gun,
        gap_guns, max_viable_guns, suggested_guns, recommendation,
        area_params, price_analysis
    )
    
    return EvaluationResult(
        supply=supply,
        demand=demand,
        supply_demand_ratio=supply_demand_ratio,
        gap_guns=gap_guns,
        recommendation=recommendation,
        suggested_guns=suggested_guns,
        suggested_fast_ratio=suggested_fast_ratio,
        estimated_daily_revenue=round(daily_revenue, 0),
        estimated_payback_months=payback_months,
        reasoning=reasoning,
        price_analysis=price_analysis,
    )


def _generate_reasoning(
    supply: SupplyInfo,
    demand: DemandEstimate,
    raw_ratio: float,
    current_kwh_per_gun: float,
    gap_guns: int,
    max_viable_guns: int,
    suggested: int,
    rec: str,
    params: dict,
    price_analysis: PriceAnalysis,
) -> str:
    """生成评估说明：简洁客观"""
    
    lines = []
    
    # === 评估结论（一句话） ===
    if current_kwh_per_gun >= 200:
        status_label = "严重缺供给"
    elif current_kwh_per_gun >= 120:
        status_label = "缺供给"
    elif current_kwh_per_gun >= 80:
        status_label = "相对平衡"
    else:
        status_label = "饱和"
    
    lines.append(f"【评估结论】该区域目前单枪度数{current_kwh_per_gun:.0f}度，相对{status_label}")
    lines.append("")
    
    # === 现有供给 ===
    lines.append("【现有供给】")
    lines.append(f"- 充电站 {supply.station_count} 座（已排除车企站和纯慢充站）")
    lines.append(f"- 快充枪 {supply.total_fast_guns} 枪，好枪 {supply.total_working_guns} 枪")
    if supply.avg_daily_kwh_per_gun > 0:
        lines.append(f"- 区域平均单枪日度数：{supply.avg_daily_kwh_per_gun:.1f} kWh")
    lines.append("")
    
    # === 价格分析（活动服务费） ===
    lines.append("【价格分析】")
    lines.append(f"- 区域活动服务费均价：{price_analysis.avg_effective_price:.2f} 元/kWh")
    lines.append(f"- 价格区间：{price_analysis.lowest_price:.2f} ~ {price_analysis.highest_price:.2f} 元/kWh")
    if price_analysis.pricing_advice:
        lines.append(f"- {price_analysis.pricing_advice}")
    lines.append("")
    
    # === 需求估算 ===
    lines.append("【需求估算】")
    lines.append(f"- 区域新能源车约 {demand.ev_count_estimate} 辆")
    lines.append(f"- 日均充电需求约 {demand.daily_charge_demand_kwh:.0f} kWh")
    lines.append("")
    
    # === 新增空间 ===
    lines.append("【新增空间】")
    lines.append(f"- 以120度/枪/日为盈利下限，区域最多容纳 {max_viable_guns} 根快充枪")
    lines.append(f"- 现有好枪 {supply.total_working_guns} 根")
    if gap_guns > 0:
        lines.append(f"- 还有约 {gap_guns} 根枪的新增空间")
        if suggested > 0:
            lines.append(f"- 建议新增规模：{suggested} 枪快充")
    else:
        lines.append("- 当前已饱和，如仍要建站需通过更低定价或更好位置抢夺份额")
    
    return "\n".join(lines)


def _influence_level_cn(level: str) -> str:
    """价格影响等级中文"""
    return {"low": "弱", "medium": "中等", "high": "强"}.get(level, "未知")


def simulate_user_station(
    supply: SupplyInfo,
    demand: DemandEstimate,
    user_guns: int,
    user_price: float = None,
) -> dict:
    """
    用户自定义模拟：输入枪数，预估建站后每日单枪可以做到多少度
    """
    if user_price is None:
        prices = [s.activity_service_fee for s in supply.stations if s.activity_service_fee]
        avg_price = sum(prices) / len(prices) if prices else 0.28
        user_price = round(avg_price * 0.95, 3)
    
    # 新站吸引力计算（假设位置在区域中心）
    prices = [s.effective_price for s in supply.stations if s.effective_price]
    avg_effective = sum(prices) / len(prices) if prices else 1.0
    max_distance = max((s.distance or 0) for s in supply.stations) if supply.stations else 3000
    
    user_effective_price = user_price + 0.55  # 服务费 + 大致加权电费
    price_score = min(avg_effective / max(user_effective_price, 0.1), 2.0) / 2.0
    distance_score = 1.0  # 中心位置
    power_score = 120 / 240.0
    rating_score = 0.8  # 新站默认
    
    user_attractiveness = (
        price_score * 0.40 + distance_score * 0.30
        + power_score * 0.15 + rating_score * 0.15
    )
    
    # 现有站总权重
    existing_weights = []
    for s in supply.stations:
        s_price_score = min(avg_effective / max(s.effective_price or 1, 0.1), 2.0) / 2.0
        s_dist_score = 1.0 - min((s.distance or 0) / max_distance, 1.0) if max_distance > 0 else 0.5
        s_power_score = min((s.power_kw or 120) / 240.0, 1.0)
        s_rating_score = (s.rating or 3.0) / 5.0
        s_attract = s_price_score * 0.4 + s_dist_score * 0.3 + s_power_score * 0.15 + s_rating_score * 0.15
        existing_weights.append(max(s_attract, 0.05) * s.working_guns)
    
    total_existing_weight = sum(existing_weights)
    user_weight = max(user_attractiveness, 0.05) * user_guns
    total_weight = total_existing_weight + user_weight
    
    # 需求分配
    user_demand_share = demand.daily_charge_demand_kwh * (user_weight / total_weight) if total_weight > 0 else 0
    predicted_kwh_per_gun = user_demand_share / user_guns if user_guns > 0 else 0
    
    # 利用率
    predicted_utilization = predicted_kwh_per_gun / (120 * 24)
    
    # 经济
    revenue_per_kwh = user_price + DEFAULT_ELECTRICITY_SPREAD
    daily_revenue = user_guns * predicted_kwh_per_gun * revenue_per_kwh
    monthly_revenue = daily_revenue * 30 * 0.7
    total_investment = user_guns * INVESTMENT_PER_GUN_FAST
    payback_months = int(total_investment / max(monthly_revenue, 1))
    
    is_viable = predicted_kwh_per_gun >= 120
    
    if is_viable:
        explanation = (
            f"预估你的{user_guns}枪站建成后，单枪日度数可达{predicted_kwh_per_gun:.0f}kWh，"
            f"超过120度盈利线，项目可行。预估回本周期约{payback_months}个月。"
        )
    else:
        explanation = (
            f"预估你的{user_guns}枪站建成后，单枪日度数约{predicted_kwh_per_gun:.0f}kWh，"
            f"低于120度盈利下限。"
        )
        if predicted_kwh_per_gun >= 80:
            explanation += "距盈利线较近，可通过更低定价或更好位置提升。"
        else:
            explanation += "建议减少枪数或寻找需求更大的区域。"
    
    return {
        "user_guns": user_guns,
        "user_service_fee": user_price,
        "predicted_daily_kwh_per_gun": round(predicted_kwh_per_gun, 1),
        "predicted_utilization": round(predicted_utilization, 3),
        "predicted_daily_revenue": round(daily_revenue, 0),
        "predicted_monthly_revenue": round(monthly_revenue, 0),
        "total_investment": total_investment,
        "payback_months": payback_months,
        "is_viable": is_viable,
        "explanation": explanation,
    }


async def run_full_evaluation(lng: float, lat: float, radius_km: float = 3.0) -> EvaluationResult:
    """
    执行完整评估流程（升级版）
    
    流程：需求→(等待避限流)→供给(传入需求用于计算利用率)→综合评估
    """
    import asyncio
    
    # 1. 先获取需求数据
    demand = await estimate_demand(lng, lat, radius_km)
    
    # 2. 等待1秒避免高德API限流
    await asyncio.sleep(1.0)
    
    # 3. 获取供给数据（传入日需求用于计算利用率和单枪度数）
    supply = await get_supply_info(
        lng, lat, radius_km,
        daily_demand_kwh=demand.daily_charge_demand_kwh
    )
    
    # 4. 计算评估结果
    result = calculate_evaluation(supply, demand)
    return result
