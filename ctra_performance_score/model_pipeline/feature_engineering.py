"""
特征工程公共模块
从 tabpfn_ctra_new.py 的 deal_data_info 中提取，供训练和预测共用。
"""
import numpy as np
import pandas as pd
import sys
import os

# 添加父目录到路径，以便导入同目录下的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ctra_performance_score.base.base_funs import time_to_minute


def process_features(data_df):
    """
    对原始 DataFrame 做特征工程，复用 deal_data_info 中的逻辑。

    输入 DataFrame 需包含以下列:
        - finish_time        : 用时 (HH:MM:SS 字符串)
        - performance_index  : 表现分 (数值，测试数据可用占位符)
        - race_end_time      : 关门时间 (HH:MM:SS 字符串)
        - aid_station        : 补给站数量
        - distance           : 距离 (km)
        - elevation_gain     : 爬升 (m)
        - elevation_loss     : 下降 (m)
        - race_year_id       : 赛事ID (可选，存在则会被删除)

    返回: 特征工程后的 DataFrame
    """
    data_df = data_df.copy()
    data_df = data_df.dropna()

    data_df['race_end_time'] = data_df['race_end_time'].apply(time_to_minute)
    data_df['finish_time'] = data_df['finish_time'].apply(time_to_minute)
    data_df = data_df.astype(float)

    # 努力公里数
    km_effort = data_df['distance'].values + data_df['elevation_gain'].values / 100
    data_df['effort_kilometer'] = km_effort

    # 补给站惩罚点
    aid_stations = data_df['aid_station'].values
    Penalty_points = []
    for i in range(len(km_effort)):
        if aid_stations[i] == 0:
            Penalty_points.append(0)
        else:
            AI = km_effort[i] / aid_stations[i]
            if AI >= 13:
                Penalty_points.append(0)
            elif AI >= 11 and AI < 13:
                Penalty_points.append(10)
            elif AI >= 9 and AI < 11:
                Penalty_points.append(15)
            elif AI >= 7 and AI < 9:
                Penalty_points.append(20)
            elif AI >= 5 and AI < 7:
                Penalty_points.append(25)
            elif AI < 5:
                Penalty_points.append(30)
    Effort_points_final = km_effort - np.array(Penalty_points)
    data_df['Effort_points_final'] = Effort_points_final

    # 衍生比率特征
    data_df['distance_rate'] = data_df['finish_time'].values / data_df['distance'].values
    data_df['gain_rate'] = data_df['finish_time'].values / data_df['elevation_gain'].values
    data_df['epf_rate'] = data_df['finish_time'].values / data_df['Effort_points_final'].values
    data_df['distance_gain_rate'] = data_df['elevation_gain'].values / data_df['distance'].values
    data_df['ekf'] = data_df['effort_kilometer'].values / data_df['finish_time'].values

    # 删除 race_year_id 列（如果存在）
    if 'race_year_id' in data_df.columns:
        data_df = data_df.drop(['race_year_id'], axis=1)

    return data_df


def get_feature_columns():
    """返回特征列名（不含 performance_index）"""
    return [
        'finish_time', 'race_end_time', 'aid_station', 'distance',
        'elevation_gain', 'elevation_loss', 'effort_kilometer',
        'Effort_points_final', 'distance_rate', 'gain_rate',
        'epf_rate', 'distance_gain_rate', 'ekf'
    ]
