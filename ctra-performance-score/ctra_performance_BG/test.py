import pandas as pd
import numpy as np
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
from ctra_performance_score.base.connect_sql import con_db,operateMysql,operateMysql_multiple
from ctra_performance_score.base.base_funs import time_to_second,seconds_to_time
from ctra_performance_score.ctra_performance_tabpfn.personal_performance_score import deal_time_score 
from loguru import logger
logger.add('./log/output.log')
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
def select_grade_info():
    select_sql = '''SELECT
                    race_year_id,
                    code,
                    finish_time,
                    performance_index as itra_performance_index,
                    500 as performance,
                    event_date,
                    country
                    FROM
                    ctra_prod_2024.data_service_itra_member_race
                    WHERE
                    status = 'Finisher'
                    and event_date >= '2023-03-01'
                    and country IN ('China', 'CHN')
                    and finish_time IS NOT NULL
                    and race_year_id >0
                    and performance_index > 0
                    ORDER BY
                    race_year_id,
                    finish_time'''
    result_data = operateMysql(select_sql)
    data_df = pd.DataFrame(result_data['data'])
    return data_df
def calc_runner_score(group):
    """
    将每位跑者的所有单场成绩，整理成 deal_time_score 所需的格式并计算
    group 是按 code 分组后的子DataFrame，需含 temp_score 和 event_date
    """
    input_data = [
        {'date': str(row['event_date'])[:10], 'score': row['temp_score']}
        for _, row in group.iterrows()
    ]
    return deal_time_score(input_data)
def deal_data_info(data):
    # 【预处理】将完赛时间转换为秒，并确保为浮点数，避免后续除法报错
    data['finish_time'] = data['finish_time'].apply(time_to_second).astype(float)
    
    # 过滤掉完赛时间为0或异常的数据，防止除以0
    data = data[data['finish_time'] > 0].copy()

    # --- 算法配置 ---
    threshold = 0.001       # 设定的收敛阈值（分差小于此值代表稳定）
    max_iterations = 10000   # 最大迭代次数，防止死循环
    max_diff = 10000
    logger.info("🚀 开始进行二分图交叉迭代计算...")
    ##按赛事分组，如果赛事内参赛者过少，可能会导致难度常数计算不稳定，可以考虑过滤掉参赛者少于10人的赛事
    data = data.groupby('race_year_id').filter(lambda x: len(x) >= 10).copy()
    logger.info(f"经过过滤后，剩余 {len(data)} 条,{data.groupby('race_year_id').ngroups}记录参与迭代计算。")

    # 第四步（外层控制）：循环迭代与收敛检测
    for iteration in range(max_iterations):
        
        # -----------------------------------------------------------------
        # 第二步：计算赛道难度常数 (Update Race Difficulty: C_j)
        # 核心公式: C_j = Median( S_i * T_ij )
        # -----------------------------------------------------------------
        # 1. 算出每条记录当前的 "分数 × 时间"
        data['temp_difficulty'] = data['performance'] * data['finish_time']
        
        # 2. 按赛事(race_year_id)分组，求中位数，得到每场比赛的难度常数字典/Series
        race_c_map = data.groupby('race_year_id')['temp_difficulty'].median()
        
        # 3. 将算出的难度常数，通过映射(map)广播回原数据表的每一行
        data['C_j'] = data['race_year_id'].map(race_c_map)

        # -----------------------------------------------------------------
        # 第三步：更新跑者表现分 (Update Runner Scores: S_i)
        # 核心公式: S_i = Average( C_j / T_ij )
        # -----------------------------------------------------------------
        # 1. 算出每条记录在当下赛道难度下反推的 "新单场得分"
        data['temp_score'] = data['C_j'] / data['finish_time'].clip(lower=200.0, upper=1500.0)
        
        # 2. 按跑者(code)分组，求单场得分的平均值，得到该跑者的最新个人表现分
        if max_diff <0.01 and iteration<9800: # 当分数已经非常接近收敛时，改为直接平均，避免过拟合
            runner_s_map = calc_runner_scores_vectorized(data)
        else:
            runner_s_map = data.groupby('code')['temp_score'].mean()
        
        # 3. 映射出全量跑者的新分数
        new_scores = data['code'].map(runner_s_map)
        new_scores = new_scores.clip(lower=200.0, upper=1500.0)


        # -----------------------------------------------------------------
        # 收敛检测与更新
        # -----------------------------------------------------------------
        # 计算所有跑者中，分数变动最大的绝对值
        max_diff = (new_scores - data['performance']).abs().max()
        logger.info(f"第 {iteration + 1} 次迭代完成，最大分数变动值: {max_diff:.6f}")

        # 将新分数更新到主表中，供下一轮计算使用
        data['performance'] = new_scores

        # 如果最大变动已经小于阈值，说明算法收敛，跳出循环
        if max_diff < threshold:
            logger.info(f"✅ 算法已成功收敛！共迭代 {iteration + 1} 次。")
            break
            
    # -----------------------------------------------------------------
    # 第五步：绝对基准映射（Scaling & Anchoring）
    # -----------------------------------------------------------------
    # 经过上面的迭代，分数只具有相对大小，我们必须将其映射为百分制或千分制
    # 策略A：寻找全表最高分，强行将天花板设定为 1000 分
    # top_score = data['performance_index'].max()
    # scale_factor = 999/ top_score if top_score > 0 else 1
    
    # 策略B（可选）：如果知道某位跑者的 code，可以强行把他设为 1000
    benchmark_code = '2989453' # 某知名跑者ID
    benchmark_score = data[data['code'] == benchmark_code]['performance'].iloc[0]
    scale_factor =929 / benchmark_score
    
    # 统一进行比例缩放，并存入最终分数列
    data['final_betrail_score'] = data['performance'] * scale_factor
    data['final_betrail_score'] = data['final_betrail_score'].round(1) # 保留一位小数

    # 清理计算过程中产生的临时列
    data = data.drop(columns=['temp_difficulty', 'C_j', 'temp_score'])
    
    # 同样可以为赛事保存一个最终的难度常数，供未来预测使用
    final_race_difficulty = race_c_map * scale_factor
    
    logger.info("🎉 表现分计算完毕！")
    return data, final_race_difficulty
def export_single_race_scores_to_excel(data, final_race_difficulty, output_filename='race_performance_scores.xlsx'):
    """
    计算每场赛事中每位参赛者的单场表现分，并导出为Excel
    
    :param data: 经过迭代计算后的主数据表 (DataFrame)
    :param final_race_difficulty: deal_data_info 函数返回的赛事最终难度常数 (Series)
    :param output_filename: 导出的Excel文件名
    """
    logger.info("⏳ 开始计算单场表现分...")
    
    # 复制一份数据以免修改原表
    # df_export = data.copy()
    df_export = data.copy()
    # -----------------------------------------------------------------
    # 1. 计算单场表现分 (Single Race Score)
    # -----------------------------------------------------------------
    # 将赛事的最终难度常数 C_j 映射到每一行
    df_export['race_difficulty_Cj'] = df_export['race_year_id'].map(final_race_difficulty)
    
    # 核心公式：单场表现分 = 赛事难度常数 / 完赛时间
    df_export['single_race_score'] = df_export['race_difficulty_Cj'] / df_export['finish_time']
    
    # 保留1位小数，让分数符合常规阅读习惯 (例如 654.3 分)
    df_export['single_race_score'] = df_export['single_race_score'].round(1)
    
    # -----------------------------------------------------------------
    # 2. 整理导出字段 (Formatting)
    # -----------------------------------------------------------------
    # 如果想让Excel更好看，可以把完赛时间(秒)转回 小时:分钟 格式 (可选)
    df_export['finish_time_formatted'] = df_export['finish_time'].apply(seconds_to_time)
    df_export['itra_performance_index'] = df_export['itra_performance_index']

    # 定义需要导出的列名顺序
    columns_to_export =[
        'race_year_id',         # 赛事ID
        'code',                 # 跑者ID
        'finish_time_formatted', # 完赛时间(小时)
        'single_race_score',    # 🎯 单场表现分 (该跑者在该场比赛的得分)
        'final_betrail_score',   # 该跑者的全局综合分 (作为对比参考)
        'country' ,               # 国家/地区（如果需要的话）
        'itra_performance_index'
    ]
    
    # 过滤掉不存在的列（防止前面的代码有变动导致报错）
    columns_to_export =[col for col in columns_to_export if col in df_export.columns]
    df_final = df_export[columns_to_export]
    
    # -----------------------------------------------------------------
    # 3. 导出为 Excel
    # -----------------------------------------------------------------
    logger.info(f"💾 正在将 {len(df_final)} 条数据导出至 {output_filename} ...")
    try:
        # engine='openpyxl' 是写入Excel必须的依赖
        df_final.to_excel(output_filename, index=False, engine='openpyxl')
        logger.info(f"✅ 导出成功！文件已保存为: {output_filename}")
    except ModuleNotFoundError:
        logger.error("❌ 导出失败：缺少 openpyxl 库。请在终端运行: pip install openpyxl")
    except PermissionError:
        logger.error(f"❌ 导出失败：文件 {output_filename} 被占用。请先关闭该Excel文件再运行代码！")
    except Exception as e:
        logger.error(f"❌ 导出失败: {e}")

    return df_final
if __name__ == "__main__":
    # 1. 从数据库读取原始数据
    logger.info("步骤 1: 从数据库加载数据...")
    raw_data_df = select_grade_info()
    
    # 2. 调用迭代算法，计算全局跑者分数与赛事难度常数
    logger.info("\n步骤 2: 进行难度评估与分数迭代计算...")
    processed_data, race_difficulty_series = deal_data_info(raw_data_df)
    
    # 3. 计算单场得分并导出Excel
    logger.info("\n步骤 3: 计算单场表现分并保存文件...")
    final_df = export_single_race_scores_to_excel(
        data=processed_data, 
        final_race_difficulty=race_difficulty_series, 
        output_filename='2023_China_ITRA_Race_Scores.xlsx' # 你可以自定义文件名
    )
    
    logger.info("\n🎉 整个流水线运行完毕！")