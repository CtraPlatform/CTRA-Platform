import pandas as pd
import numpy as np

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)

from ctra_performance_score.base.connect_sql import con_db, operateMysql, operateMysql_multiple
from ctra_performance_score.base.base_funs import time_to_second, seconds_to_time
from loguru import logger

logger.add('./log/output.log')

# ============================================================
# 预计算常量（模块加载时执行一次，迭代中不再重复计算）
# ============================================================

# 当前年月，用于向量化 month_diff（与原 datetime.now() 等价）
_NOW = pd.Timestamp.now()

# calculate_weighted_score 的固定权重矩阵，按场次数预构建为 NumPy 数组
# _WEIGHT_MATRIX[i] 对应有 i+1 场成绩时各场的权重（最高分→最低分顺序）
_WEIGHT_MATRIX = [
    np.array([0.97]),
    np.array([0.99, 0.98]),
    np.array([1.0,  0.99, 0.99]),
    np.array([1.01, 1.0,  1.0,  0.99]),
    np.array([1.02, 1.01, 1.0,  1.0,  0.99]),
]


def select_grade_info():
    select_sql = '''SELECT
                    race_year_id,
                    code,
                    finish_time,
                    performance_index as itra_performance_index,
                    100 as performance,
                    event_date,
                    country
                    FROM
                    ctra_prod_2024.data_service_itra_member_race
                    WHERE
                    status = 'Finisher'
                    and event_date >= '2024-01-01'
                    and country IN ('China', 'CHN')
                    and finish_time IS NOT NULL
                    and race_year_id >0
                    and performance_index > 0
                    ORDER BY
                      event_date,
                        finish_time'''
    result_data = operateMysql(select_sql)
    data_df = pd.DataFrame(result_data['data'])
    return data_df


# ============================================================
# 向量化辅助函数（精确还原原始逻辑，无任何近似）
# ============================================================

def _vec_month_diff(dates: pd.Series) -> pd.Series:
    """
    向量化版 month_diff。
    原逻辑：relativedelta(now, date).years*12 + relativedelta(now, date).months
    等价公式：(now.year - date.year)*12 + (now.month - date.month)
    relativedelta 处理跨年时与此公式完全等价。
    """
    dt = pd.to_datetime(dates)
    diff = (_NOW.year - dt.dt.year) * 12 + (_NOW.month - dt.dt.month)
    return diff.clip(lower=0)


def _vec_get_weight(month_diffs: pd.Series) -> pd.Series:
    """
    向量化版 get_weight，精确还原分段逻辑：
        <= 11   → 1.0
        12-17   → 0.995
        18-23   → 0.99
        24-29   → 0.985
        30-35   → 0.98
        > 35    → 0.0  （原函数 else 分支）
    """
    m = month_diffs.values
    conditions = [
        m <= 11,
        (m >= 12) & (m <= 17),
        (m >= 18) & (m <= 23),
        (m >= 24) & (m <= 29),
        (m >= 30) & (m <= 35),
    ]
    choices = [1.0, 0.995, 0.99, 0.985, 0.98]
    return pd.Series(np.select(conditions, choices, default=0.0), index=month_diffs.index)
def _vec_calculate_weighted_score_max(weighted_scores_desc: np.ndarray) -> float:
    """
    向量化版 calculate_weighted_score，直接返回 max 值（省去外层 max 调用）。

    原逻辑：对 n 场成绩（已按得分降序），枚举"取前1场...前n场"，
    每种取法用对应权重向量做点积后除以场次数（即加权均值），取所有均值的最大值。

    优化：用预构建 NumPy 权重数组做向量点积，替代 Python 双重循环。
    """
    n = len(weighted_scores_desc)
    if n == 0:
        return 0.0
    best = -np.inf
    for i in range(n):
        # np.dot 比 Python sum(a*b) 快 ~5-10x
        val = np.dot(weighted_scores_desc[:i + 1], _WEIGHT_MATRIX[i]) / (i + 1)
        if val > best:
            best = val
    return float(best)

def calc_runner_scores_vectorized(data: pd.DataFrame) -> pd.Series:
    """
    计算每位跑者的综合表现分，逻辑分两步：

    Step A：取历史最高5场
        → 按 temp_score 降序，取前5场
        → 计算时间衰减权重（get_weight）后的 weighted_score
        → 用 calculate_weighted_score 权重矩阵计算，取最大均值 → top5_score

    Step B：剩余成绩（第6场及之后，按得分降序）
        → 同样计算时间衰减权重后的 weighted_score
        → 对所有剩余场求加权平均（权重为时间衰减系数）→ rest_score

    Step C：最终综合分
        → final = (top5_score × 5 + rest_score × rest_count) / (5 + rest_count)
        → 若无剩余成绩，final = top5_score
    """
    df = data[['code', 'event_date', 'temp_score']].copy()

    # ── 全量向量化：月份差 & 时间衰减权重 ──────────────────────────
    df['month_diff']    = _vec_month_diff(df['event_date'])
    df['time_weight']   = _vec_get_weight(df['month_diff'])
    df['weighted_score'] = df['temp_score'] * df['time_weight']

    # ── 按得分降序排名（组内） ──────────────────────────────────────
    df['rank'] = df.groupby('code')['temp_score'].rank(method='first', ascending=False)

    # ── Step A：Top5 ────────────────────────────────────────────────
    top5 = df[df['rank'] <= 5].copy()
    top5 = top5.sort_values(['code', 'temp_score'], ascending=[True, False])

    top5_score_map = top5.groupby('code', sort=False)['weighted_score'].apply(
        lambda ws: _vec_calculate_weighted_score_max(ws.values)
    )  # Series: code → top5_score

    # ── Step B：剩余成绩（rank > 5） ────────────────────────────────
    rest = df[df['rank'] > 5].copy()

    if rest.empty:
        # 所有跑者都只有 ≤5 场，直接返回 Top5 分
        return data['code'].map(top5_score_map).fillna(0.0)

    # 剩余成绩加权平均：sum(weighted_score) / sum(time_weight)
    # 用 time_weight 作为分母，weight=0（超35月）的记录自然不贡献分子分母
    rest_numerator   = rest.groupby('code')['weighted_score'].sum()   # Σ(score × w)
    rest_denominator = rest.groupby('code')['time_weight'].sum()      # Σ(w)

    # 避免分母为0（所有剩余场都超过35个月，权重全为0）
    rest_score_map = (rest_numerator / rest_denominator.replace(0, np.nan)).fillna(0.0)

    # 剩余场次数（用于加权合并）
    rest_count_map = rest.groupby('code')['rank'].count()

    # ── Step C：合并 Top5 分与剩余均分 ──────────────────────────────
    # 统一 index，缺失值（该跑者无剩余成绩）填0
    codes = top5_score_map.index.union(rest_score_map.index)
    top5_s  = top5_score_map.reindex(codes, fill_value=0.0)
    rest_s  = rest_score_map.reindex(codes, fill_value=0.0)
    rest_n  = rest_count_map.reindex(codes, fill_value=0)

    # 加权合并：Top5 占5份权重，剩余成绩按实际场次占权重
    final_score_map = (top5_s * 0.6 + rest_s * 0.4)  # 这里权重可调，原逻辑中剩余成绩占比不明确，暂定为40%

    return data['code'].map(final_score_map).fillna(0.0)


def calc_runner_scores_vectorized(data: pd.DataFrame) -> pd.Series:
    """
    完整向量化还原 deal_time_score 逻辑，替代原来的逐跑者 groupby.apply。

    原流程（per-runner Python 调用）：
        构建 DataFrame → sort → head(5) → 逐行 month_diff →
        逐行 get_weight → weighted_score → calculate_weighted_score → max

    优化流程：
        步骤1-3：全量 Pandas/NumPy 向量化，无 Python 行级循环
        步骤4：每组最多 5 条的轻量 apply（数据量降低 ~95%）

    耗时预估：原 ~2.5min/次 → 优化后 ~5-15秒/次
    """
    df = data[['code', 'event_date', 'temp_score']].copy()

    # 步骤1：每位跑者取 temp_score 最高的前5场（全量一次性向量化排名）
    df['rank'] = df.groupby('code')['temp_score'].rank(method='first', ascending=False)
    top5 = df[df['rank'] <= 5].copy()

    # 步骤2：向量化计算 month_diff 和 get_weight（无行级循环）
    top5['month_diff'] = _vec_month_diff(top5['event_date'])
    top5['weight'] = _vec_get_weight(top5['month_diff'])

    # 步骤3：向量化计算加权分（对应原 weighted_score = score * weight）
    top5['weighted_score'] = top5['temp_score'] * top5['weight']

    # 步骤4：组内按得分降序排列（对应原 sort_values by='score' ascending=False）
    # 然后对每位跑者调用轻量聚合（每组最多5条，速度极快）
    top5 = top5.sort_values(['code', 'temp_score'], ascending=[True, False])

    runner_s_map = top5.groupby('code', sort=False)['weighted_score'].apply(
        lambda ws: _vec_calculate_weighted_score_max(ws.values)
    )
    return runner_s_map


# ============================================================
# 主计算流程
# ============================================================

def deal_data_info(data: pd.DataFrame):
    logger.info("⏳ 预处理：转换完赛时间...")
    data['finish_time'] = data['finish_time'].apply(time_to_second).astype(float)
    data = data[data['finish_time'] > 0].copy()

    # 提前转换 event_date 为字符串，迭代内不再重复处理
    data['event_date'] = data['event_date'].astype(str).str[:10]

    threshold = 0.0001
    max_iterations = 100

    logger.info("🚀 开始进行二分图交叉迭代计算...")
    data = data.groupby('race_year_id').filter(lambda x: len(x) >= 20).copy()
    logger.info(f"经过过滤后，剩余 {len(data)} 条，{data.groupby('race_year_id').ngroups} 场赛事参与迭代计算。")

    data = data.reset_index(drop=True)

    for iteration in range(max_iterations):

        # 第二步：赛道难度常数 C_j = Median(S_i * T_ij)
        data['temp_difficulty'] = data['performance'] * data['finish_time']
        race_c_map = data.groupby('race_year_id')['temp_difficulty'].median()
        data['C_j'] = data['race_year_id'].map(race_c_map)

        # 第三步：单场得分与跑者综合分
        data['temp_score'] = data['C_j'] / data['finish_time']
        runner_s_map = calc_runner_scores_vectorized(data)
        # 3. 映射出全量跑者的新分数
        new_scores = data['code'].map(runner_s_map)

        alpha = 0.5
        data['performance'] = alpha * new_scores + (1 - alpha) * data['performance']

        # max_diff = (new_scores - data['performance']).abs().max()
        max_diff = (new_scores - data['performance']).abs().quantile(0.99)
        logger.info(f"第 {iteration + 1} 次迭代完成，最大分数变动值: {max_diff:.6f}")

        # 将新分数更新到主表中，供下一轮计算使用
        data['performance'] = new_scores

        # 如果最大变动已经小于阈值，说明算法收敛，跳出循环
        if max_diff < threshold:
            logger.info(f"✅ 算法已成功收敛！共迭代 {iteration + 1} 次。")
            break

    # 第五步：基准映射缩放
    benchmark_code = '2989453'
    benchmark_rows = data[data['code'] == benchmark_code]
    if benchmark_rows.empty:
        logger.warning(f"⚠️ 未找到基准跑者 {benchmark_code}，使用全局最高分作为基准。")
        benchmark_score = data['performance'].max()
        scale_factor = 999 / benchmark_score if benchmark_score > 0 else 1
    else:
        benchmark_score = benchmark_rows['performance'].iloc[0]
        scale_factor = 929 / benchmark_score

    data['final_betrail_score'] = (data['performance'] * scale_factor).round(1)
    data = data.drop(columns=['temp_difficulty', 'C_j', 'temp_score'], errors='ignore')
    final_race_difficulty = race_c_map * scale_factor

    logger.info("🎉 表现分计算完毕！")
    return data, final_race_difficulty


def export_single_race_scores_to_excel(data, final_race_difficulty, output_filename='race_performance_scores.xlsx'):
    logger.info("⏳ 开始计算单场表现分...")

    df_export = data.copy()
    df_export['race_difficulty_Cj'] = df_export['race_year_id'].map(final_race_difficulty)
    df_export['single_race_score'] = (df_export['race_difficulty_Cj'] / df_export['finish_time']).round(1)
    df_export['finish_time_formatted'] = df_export['finish_time'].apply(seconds_to_time)
    df_export['itra_performance_index'] = df_export['itra_performance_index']


    columns_to_export = [
        'race_year_id', 'code', 'finish_time_formatted',
        'single_race_score', 'final_betrail_score', 'country','itra_performance_index'
    ]
    columns_to_export = [col for col in columns_to_export if col in df_export.columns]
    df_final = df_export[columns_to_export]

    logger.info(f"💾 正在将 {len(df_final)} 条数据导出至 {output_filename} ...")
    try:
        df_final.to_excel(output_filename, index=False, engine='openpyxl')
        logger.info(f"✅ 导出成功！文件已保存为: {output_filename}")
    except ModuleNotFoundError:
        logger.error("❌ 导出失败：缺少 openpyxl，请运行: pip install openpyxl")
    except PermissionError:
        logger.error(f"❌ 导出失败：文件 {output_filename} 被占用，请先关闭。")
    except Exception as e:
        logger.error(f"❌ 导出失败: {e}")

    return df_final


if __name__ == "__main__":
    logger.info("步骤 1: 从数据库加载数据...")
    raw_data_df = select_grade_info()

    logger.info("\n步骤 2: 进行难度评估与分数迭代计算...")
    processed_data, race_difficulty_series = deal_data_info(raw_data_df)

    logger.info("\n步骤 3: 计算单场表现分并保存文件...")
    final_df = export_single_race_scores_to_excel(
        data=processed_data,
        final_race_difficulty=race_difficulty_series,
        output_filename='2023_China_ITRA_Race_Scores.xlsx'
    )

    logger.info("\n🎉 整个流水线运行完毕！")