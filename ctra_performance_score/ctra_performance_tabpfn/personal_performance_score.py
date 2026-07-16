'''
计算个人综合表现分
input:36个月内的所有比赛日期和成绩
output:个人综合表现分
'''
import datetime
from ctra_performance_score.base.connect_sql import con_db,operateMysql,operateMysql_multiple
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
from loguru import logger
###输入日期字符串，返回距今过去了多少月
def month_diff(date_str):
    date_format = "%Y-%m-%d"
    input_date = datetime.datetime.strptime(date_str, date_format)
    current_date = datetime.datetime.now()
    delta = relativedelta(current_date, input_date)
    total_months = delta.years * 12 + delta.months
    return total_months
###根据月份差值返回权重
'''
距今月份
权重
0-11
1
12-17
0.995
18-23
0.99
24-29
0.985
30-35
0.98
'''
def get_weight(month_diff):
    if month_diff <= 11:
        return 1
    elif 12 <= month_diff <= 17:
        return 0.995
    elif 18 <= month_diff <= 23:
        return 0.99
    elif 24 <= month_diff <= 29:
        return 0.985
    elif 30 <= month_diff <= 35:
        return 0.98
    else:
        return 0
###对成绩进行加权处理，输出综合表现分
'''
第一场	第二场	第三场	第四场	第五场
0.97	0.99	1	1.01	1.02
        0.98	0.99	1	1.01
                0.99	1	1
                        0.99	1
                            0.99

'''
def calculate_weighted_score(weighted_scores):
    results = []
    n = len(weighted_scores)
    weight = [[0.97],[0.99,0.98],[1,0.99,0.99],[1.01,1,1,0.99],[1.02,1.01,1,1,0.99]]
    for i in range(n):
        result = []
        for j in range(i+1):
            result.append(weighted_scores[j]*weight[i][j])
        results.append(result)
    score = []
    for r in results:
        score.append((np.mean(r)))
        # score.append(np.floor(np.mean(r)))
    

    return score


def deal_time_score(input_data):
    '''对所有成绩进行排序输出前5名'''
    input_data_sort = pd.DataFrame(input_data).sort_values(by='score',ascending=False).head(5)
    input_data_sort['month_diff'] = input_data_sort['date'].apply(month_diff)
    input_data_sort['weight'] = input_data_sort['month_diff'].apply(get_weight)
    input_data_sort['weighted_score'] = input_data_sort['score'] * input_data_sort['weight']
    weighted_scores = calculate_weighted_score(input_data_sort['weighted_score'].values)
    if len(weighted_scores) ==0:
        return 0
    else:
        return max (weighted_scores)
##读取用户信息以及历史成绩
def select_user_data(data_service_race_info_id):
    data_service_race_info_id =  ', '.join(map(str, data_service_race_info_id))
    race_date = (datetime.datetime.now().date() - relativedelta(months=36)).strftime("%Y-%m-%d")
    select_sql = f"""
        SELECT
            di.card,
            dr.ctra_performance_index as score,
            dr.race_date as date
        FROM
            ctra_prod_2024.data_service_member_info di
        left join ctra_prod_2024.data_service_member_race dr on di.card = dr.card 
        where 
        dr.race_date >= '{race_date}'
        and dr.ctra_performance_index IS NOT null
        and dr.data_service_race_info_id in ({data_service_race_info_id})
        order by di.card
    """

    
    select_result = operateMysql(select_sql)
    if select_result['msg'] == 'success':
        data = pd.DataFrame(select_result['data'])
        return data
    else:
        return pd.DataFrame()
##更新用户综合表现分
def update_user_performance_score(card,performance_score):
    update_sql = f"""
        update ctra_prod_2024.data_service_member_info
        set ctra_performance_index = {performance_score}
        where card = '{card}'
    """
    update_result = operateMysql(update_sql)
    if update_result['msg'] == 'success':
        logger.info(f"用户{card}综合表现分更新成功")
    else:
        logger.info(f"用户{card}综合表现分更新失败: {update_result['error']}")
# def calculate_personal_performance_score(data_service_race_info_id):
#     race_info = select_user_data(data_service_race_info_id)
#     # input_data = [
#     #     {'date': '2025-10-25', 'score': 504},
#     #     {'date': '2025-08-03', 'score': 489},
#     #     {'date': '2023-09-17', 'score': 483},
#     #     {'date': '2025-07-12', 'score': 459},
#     #     {'date': '2023-07-08', 'score': 457},
#     #     {'date': '2024-05-01', 'score': 449}
#     # ]
#     card_ids = race_info['card'].unique()
#     input_data = []
#     # card_ids = ['511502199112285226']
#     logger.info(f"需要计算综合表现分的用户数量: {len(card_ids)}")
#     for i, card in enumerate(card_ids):
#         user_data = race_info[race_info['card'] == card]
#         final_score = deal_time_score(user_data)
#         update_user_performance_score(card,final_score)
#         logger.info(f"第{i}个人综合表现分: {final_score}")
import multiprocessing
from functools import partial
import os
def _process_user(card_id, user_data):
    """模块级可序列化的处理函数（避免局部函数问题）"""
    try:
        final_score = deal_time_score(user_data)
        update_user_performance_score(card_id, final_score)
        # 使用进程ID区分日志（避免多进程日志交错）
        # logger.info(f"[PID:{os.getpid()}] {card_id} -> {final_score}")
        return (card_id, final_score)
    except Exception as e:
        logger.error(f"用户 {card_id} 处理失败: {str(e)}")
        return (card_id, None)

def calculate_personal_performance_score(data_service_race_info_id):
    race_info = select_user_data(data_service_race_info_id)
    card_ids = race_info['card'].unique()
    logger.info(f"需要计算综合表现分的用户数量: {len(card_ids)}")
    
    # 如果用户数量 <= 1，直接顺序执行
    if len(card_ids) <= 1:
        for i, card in enumerate(card_ids):
            user_data = race_info[race_info['card'] == card]
            final_score = deal_time_score(user_data)
            update_user_performance_score(card, final_score)
            # logger.info(f"第{i}个人综合表现分: {final_score}")
        logger.info(f"{data_service_race_info_id}所有用户计算完成")
        return
    
    # 准备用户数据分组（仅传递必要数据）
    user_groups = [(card, race_info[race_info['card'] == card]) for card in card_ids]
    
    # 智能设置进程数（避免过度开销）
    num_processes = min(multiprocessing.cpu_count(), len(user_groups))
    logger.info(f"启用 {num_processes} 个进程并行计算")
    
    # 使用进程池并行处理（关键：使用模块级函数）
    with multiprocessing.Pool(processes=num_processes) as pool:
        results = pool.starmap(_process_user, user_groups)
    
    # 汇总处理结果
    failed_users = [card for card, score in results if score is None]
    if failed_users:
        logger.error(f"失败的用户: {failed_users}")
    
    logger.info("所有用户计算完成")
# 示例输入
if __name__ == "__main__":
    input_str = input("请输入用逗号分隔的赛事id（如：1,2,3,4）: ")
    data_service_race_info_id = list(map(int, input_str.split(',')))
    logger.info(f"输入的赛事id是: {data_service_race_info_id}")
    # data_service_race_info_id = [140]
    calculate_personal_performance_score(data_service_race_info_id)
    


