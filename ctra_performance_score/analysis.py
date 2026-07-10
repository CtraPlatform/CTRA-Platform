"""
基于 performance_index 的 XGBoost 回归训练脚本。
使用 `deal_data_info(itest_race_date)` 生成的数据进行训练，
并按数据出现顺序将最后一个 `race_year_id` 分组作为测试集。
"""

import pandas as pd
import numpy as np
from loguru import logger

try:
    import xgboost as xgb
    XGBOOST_IMPORT_ERROR = None
except ImportError as exc:
    xgb = None
    XGBOOST_IMPORT_ERROR = exc

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)

from connect_sql import con_db, operateMysql
from base_funs import time_to_minute


def select_data_info(test_race_date=None):
    con_db()
    sql = f'''SELECT
                a.race_year_id,
                a.finish_time,
                a.performance_index,
                b.race_end_time,
                b.aid_station,
                b.distance,
                b.elevation_gain,
                b.elevation_loss
            FROM
                ctra_prod_2024.data_service_itra_member_race a
                left join ctra_prod_2024.data_service_itra_race_info b on (a.race_year_id = b.race_year_id)
            WHERE
                performance_index > 0
                AND (ranking LIKE '1 / %'
                    AND (country = 'China' ))
                and aid_station > 0 and effort_kilometer > 10
                AND a.race_year_id NOT IN (00)
                and a.event_date < '{test_race_date}'
            ORDER BY
                a.event_date'''
    res = operateMysql(sql)
    return res


def deal_data_info(itest_race_date=None, keep_group_col=True):
    res = select_data_info(itest_race_date)
    select_data = res['data']
    data_df = pd.DataFrame(select_data)

    if data_df.empty:
        raise ValueError('未查询到可用于训练的数据。')

    data_df = data_df.dropna().copy()
    data_df['race_end_time'] = data_df['race_end_time'].apply(time_to_minute)
    data_df['finish_time'] = data_df['finish_time'].apply(time_to_minute)
    data_df = data_df.astype(float)

    km_effort = data_df['distance'].values + data_df['elevation_gain'].values / 100
    data_df['effort_kilometer'] = km_effort
    aid_stations = data_df['aid_station'].values
    penalty_points = []

    for i in range(len(km_effort)):
        if aid_stations[i] == 0:
            penalty_points.append(0)
        else:
            ai_value = km_effort[i] / aid_stations[i]
            if ai_value >= 13:
                penalty_points.append(0)
            elif 11 <= ai_value < 13:
                penalty_points.append(10)
            elif 9 <= ai_value < 11:
                penalty_points.append(15)
            elif 7 <= ai_value < 9:
                penalty_points.append(20)
            elif 5 <= ai_value < 7:
                penalty_points.append(25)
            else:
                penalty_points.append(30)

    data_df['Effort_points_final'] = km_effort - np.array(penalty_points)
    data_df['distance_rate'] = data_df['finish_time'].values / data_df['distance'].values
    data_df['gain_rate'] = data_df['finish_time'].values / data_df['elevation_gain'].values
    data_df['epf_rate'] = data_df['finish_time'].values / data_df['Effort_points_final'].values
    data_df['ekf'] = data_df['effort_kilometer'].values / data_df['finish_time'].values
    data_df['distance_gain_rate'] = data_df['elevation_gain'].values / data_df['distance'].values
    if not keep_group_col:
        data_df = data_df.drop(['race_year_id'], axis=1)

    return data_df


def split_last_n_as_test(data_df, test_size=5, group_col='race_year_id', target_col='performance_index'):
    if group_col not in data_df.columns:
        raise ValueError(f'数据中缺少分组列: {group_col}')
    if target_col not in data_df.columns:
        raise ValueError(f'数据中缺少目标列: {target_col}')
    if len(data_df) <= test_size:
        raise ValueError(f'数据量不足，至少需要大于 {test_size} 条记录才能切分训练集和测试集。')

    train_df = data_df.iloc[:-test_size].copy()
    test_df = data_df.iloc[-test_size:].copy()

    feature_cols = [col for col in data_df.columns if col not in [group_col, target_col]]
    X_train = train_df[feature_cols]
    y_train = train_df[target_col]
    X_test = test_df[feature_cols]
    y_test = test_df[target_col]

    return X_train, X_test, y_train, y_test, test_df[[group_col]].copy(), feature_cols


def train_xgboost_model(X_train, y_train):
    if xgb is None:
        raise ImportError(
            '当前环境未安装 xgboost，请先执行 `python3 -m pip install xgboost` 后再运行。'
        ) from XGBOOST_IMPORT_ERROR

    dtrain = xgb.DMatrix(X_train, label=y_train)
    params = {
        'objective': 'reg:squarederror',
        'eval_metric': 'rmse',
        'eta': 0.05,
        'max_depth': 6,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'seed': 42,
    }
    model = xgb.train(params=params, dtrain=dtrain, num_boost_round=300)
    return model


def evaluate_regression(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mae = np.mean(np.abs(y_true - y_pred))
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))

    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan

    return {
        'mae': mae,
        'rmse': rmse,
        'r2': r2,
    }


def run_xgboost_training(itest_race_date='2026-03-01', test_size=1):
    df = deal_data_info(itest_race_date, keep_group_col=True)
    X_train, X_test, y_train, y_test, test_meta, feature_cols = split_last_n_as_test(df, test_size=test_size)
    model = train_xgboost_model(X_train, y_train)
    dtest = xgb.DMatrix(X_test)
    y_pred = model.predict(dtest)
    metrics = evaluate_regression(y_test, y_pred)

    result_df = X_test.copy()
    result_df['y_true'] = y_test.values
    result_df['y_pred'] = y_pred
    result_df['race_year_id'] = test_meta['race_year_id'].values

    logger.info(f'总样本数: {len(df)}')
    logger.info(f'特征列: {feature_cols}')
    logger.info(f'训练集样本数: {len(X_train)}')
    logger.info(f'测试集样本数: {len(X_test)}')
    logger.info(f'测试集 race_year_id 列表: {test_meta["race_year_id"].tolist()}')
    logger.info(f"MAE: {metrics['mae']:.4f}")
    logger.info(f"RMSE: {metrics['rmse']:.4f}")
    logger.info(f"R2: {metrics['r2']:.4f}")
    logger.info(f'测试集预测结果:\n{result_df}')

    return model, metrics, result_df


if __name__ == '__main__':
    itest_race_date = '2025-07-01'
    run_xgboost_training(itest_race_date)
