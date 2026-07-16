"""
预测脚本
====================
读取本地保存的模型组件，读取 Excel 中的赛事信息，
代入训练好的 TabPFN 模型输出表现分预测结果。

用法:
    python predict_from_excel.py --excel races.xlsx
    python predict_from_excel.py --excel races.xlsx --output predictions.xlsx
    python predict_from_excel.py --excel races.xlsx --model-dir ./saved_model

Excel 格式要求（两个 sheet 页）:

 sheet 页 "赛事信息"（列名）:
    | race_end_time | aid_station | distance | elevation_gain | elevation_loss |
    |---------------|-------------|----------|----------------|----------------|
    | 24:00:00      | 5           | 50       | 3000           | 2800           |
    - race_end_time  : 关门时间 (HH:MM:SS)
    - aid_station    : 补给站数量
    - distance       : 距离 (km)
    - elevation_gain : 爬升 (m)
    - elevation_loss : 下降 (m，正数)

 sheet 页 "赛事成绩信息"（列名）:
    | 姓名  | finish_time |
    |-------|-------------|
    | 张三  | 06:30:00    |
    | 李四  | 07:15:00    |
    - 姓名        : 选手姓名
    - finish_time : 完赛用时 (HH:MM:SS)
"""
import os
import sys
import pickle
import argparse
import numpy as np
import pandas as pd
from loguru import logger

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ctra_performance_score.ctra_performance_tabpfn.models import dayahead_info_cluster
from feature_engineering import process_features
from ctra_performance_score.base.base_funs import time_to_second

# TabPFN
try:
    from tabpfn import TabPFNRegressor
except ImportError:
    TabPFNRegressor = None
    logger.warning("tabpfn 未安装，请执行 pip install tabpfn")

DEFAULT_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_model')
DEFAULT_CKPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tabpfn-v2-regressor.ckpt')

# TabPFN 训练时取 top-N 样本数（与原代码一致）
TOP_N = 100

SHEET_RACE_INFO = '赛事信息'
SHEET_MEMBER_RESULT = '赛事成绩信息'


def load_model(model_dir):
    """加载本地保存的模型组件"""
    logger.info(f"从 {model_dir} 加载模型组件...")

    components = {}
    for name in ['train_df', 'scaler_X', 'scaler_y', 'selected_indices', 'performance_model_info']:
        path = os.path.join(model_dir, f'{name}.pkl')
        if not os.path.exists(path):
            raise FileNotFoundError(f"模型文件不存在: {path}")
        with open(path, 'rb') as f:
            components[name] = pickle.load(f)

    logger.info(f"模型加载完成 | 训练样本数: {components['performance_model_info']['n_samples']} | "
                f"截止日期: {components['performance_model_info']['cutoff_date']}")
    return components


def create_tabpfn_regressor():
    """创建 TabPFNRegressor，优先使用本地 checkpoint"""
    if TabPFNRegressor is None:
        raise ImportError("tabpfn 未安装，请执行 pip install tabpfn")

    reg_kwargs = {
        'device': 'cpu',
        'random_state': 42,
        'ignore_pretraining_limits': True,
    }
    if os.path.exists(DEFAULT_CKPT):
        reg_kwargs['model_path'] = DEFAULT_CKPT
        logger.info(f"使用本地 checkpoint: {DEFAULT_CKPT}")

    return TabPFNRegressor(**reg_kwargs)


def read_excel_data(excel_path):
    """
    读取 Excel 中的两个 sheet 页:
        - "赛事信息": race_end_time, aid_station, distance, elevation_gain, elevation_loss
        - "赛事成绩信息": 姓名, finish_time

    返回:
        race_info_df : 赛事信息 DataFrame（每行一个赛事）
        member_df    : 赛事成绩信息 DataFrame（每行一名选手）
    """
    logger.info(f"读取 Excel: {excel_path}")

    # 读取赛事信息 sheet
    race_info_df = pd.read_excel(excel_path, sheet_name=SHEET_RACE_INFO)
    required_race_cols = ['race_end_time', 'aid_station', 'distance',
                          'elevation_gain', 'elevation_loss']
    missing = [c for c in required_race_cols if c not in race_info_df.columns]
    if missing:
        raise ValueError(f"sheet '{SHEET_RACE_INFO}' 缺少必要列: {missing}，需要的列: {required_race_cols}")
    logger.info(f"读取到 {len(race_info_df)} 条赛事信息")

    # 读取赛事成绩信息 sheet
    member_df = pd.read_excel(excel_path, sheet_name=SHEET_MEMBER_RESULT)
    required_member_cols = ['姓名', 'finish_time']
    missing = [c for c in required_member_cols if c not in member_df.columns]
    if missing:
        raise ValueError(f"sheet '{SHEET_MEMBER_RESULT}' 缺少必要列: {missing}，需要的列: {required_member_cols}")
    logger.info(f"读取到 {len(member_df)} 条赛事成绩信息")

    return race_info_df, member_df


def build_predict_input(race_info_row, first_finish_time):
    """
    将赛事信息行和第一条 finish_time 拼接成模型预测所需的输入格式。

    返回单行 DataFrame，包含:
        finish_time, performance_index(占位), race_end_time, aid_station,
        distance, elevation_gain, elevation_loss, race_year_id(占位)
    """
    input_data = {
        'race_year_id': '1111',
        'finish_time': first_finish_time,
        'performance_index': 1000,
        'race_end_time': race_info_row['race_end_time'],
        'aid_station': race_info_row['aid_station'],
        'distance': race_info_row['distance'],
        'elevation_gain': race_info_row['elevation_gain'],
        'elevation_loss': race_info_row['elevation_loss'],
    }
    return pd.DataFrame([input_data])


def predict_single(test_row, model_components):
    """
    对单条赛事数据做预测，复用 forecast_point_fun 的核心逻辑。

    流程:
        1. 将测试数据与训练数据合并
        2. 用保存的 scaler 标准化
        3. 用保存的 selected_indices 选择特征
        4. 聚类，选择与测试数据同类的训练样本
        5. 取 top-N 样本，TabPFN 预测
        6. 反标准化得到表现分
    """
    train_df = model_components['train_df']
    scaler_X = model_components['scaler_X']
    scaler_y = model_components['scaler_y']
    selected_indices = model_components['selected_indices']

    # ===== 1. 测试数据特征工程 =====
    test_df = process_features(test_row)
    if len(test_df) == 0:
        raise ValueError("测试数据特征工程后为空，请检查数据（可能含 NaN）")

    # ===== 2. 合并训练数据和测试数据 =====
    common_cols = [c for c in train_df.columns if c in test_df.columns]
    train_aligned = train_df[common_cols]
    test_aligned = test_df[common_cols]
    combined_df = pd.concat([train_aligned, test_aligned], ignore_index=True)

    # ===== 3. 分离 X / y =====
    y_all = combined_df['performance_index'].values
    X_all = combined_df.drop(['performance_index'], axis=1).values

    # ===== 4. 标准化（使用训练时 fit 的 scaler）=====
    X_scaled = scaler_X.transform(X_all)
    y_scaled = scaler_y.transform(y_all.reshape(-1, 1)).flatten()

    # ===== 5. 特征选择（使用训练时计算的索引）=====
    X_selected = X_scaled[:, selected_indices]

    # ===== 6. 聚类，选择与测试数据（最后一个样本）同类的训练数据 =====
    cluster_data, index = dayahead_info_cluster(X_selected)
    index = index.tolist()
    index.sort(reverse=False)

    inpult_data_x = X_selected[index[:-1]]
    inpult_data_y = y_scaled[index[:-1]]

    logger.info(f"同类别数量: {len(index)}")

    # ===== 7. 取 top-N 样本 =====
    if len(index) > TOP_N:
        sorted_indices = np.argsort(-inpult_data_y)
        top_n_indices = sorted_indices[:TOP_N]
        inpult_data_y = inpult_data_y[top_n_indices]
        inpult_data_x = inpult_data_x[top_n_indices]

    # ===== 8. TabPFN 预测 =====
    test_data = X_selected[-1]

    tab_model = create_tabpfn_regressor()
    tab_model.fit(inpult_data_x, inpult_data_y)
    y_hat = tab_model.predict(test_data.reshape((1, -1)))

    # ===== 9. 反标准化 =====
    y_pred_inv = scaler_y.inverse_transform(y_hat.reshape((1, -1)))
    y_pred = np.array(y_pred_inv).reshape(-1)

    # ===== 10. 计算 finish_level =====
    test_info = test_df.iloc[0].astype(float).to_dict()
    finish_level = np.ceil(test_info['finish_time'] * y_pred[0] / test_info['race_end_time'])

    return float(y_pred[0]), float(finish_level)


def calculate_all_scores(member_df, y_pred):
    """
    根据预测表现分 p 和所有选手的 finish_time 计算每位选手的成绩。
    参数:
        member_df : 赛事成绩信息 DataFrame，需包含 '姓名' 和 'finish_time' 列
        y_pred    : 预测表现分

    返回:
        member_result_df : 包含 姓名、finish_time、predicted_score 的 DataFrame
    """
    finish_times = member_df['finish_time'].tolist()
    # 转为秒
    finish_seconds = [time_to_second(ft) for ft in finish_times]

    scores = np.zeros(len(member_df))
    scores[0] = y_pred
    for i in range(1, len(member_df)):
        if finish_seconds[i] == 0:
            logger.warning(f"第 {i+1} 名选手 finish_time 转秒为 0，跳过计算")
            scores[i] = scores[i - 1]
        else:
            scores[i] = finish_seconds[i - 1] * scores[i - 1] / finish_seconds[i]

    result_df = member_df[['姓名', 'finish_time']].copy()
    result_df['predicted_score'] = np.round(scores).astype(int)
    return result_df


def predict_batch(excel_path, model_dir=None, output_path=None):
    """
    读取 Excel（两个 sheet 页），预测表现分并计算所有选手成绩，输出结果到 Excel。
    """
    if model_dir is None:
        model_dir = DEFAULT_MODEL_DIR

    # 加载模型
    components = load_model(model_dir)

    # 读取 Excel 两个 sheet
    race_info_df, member_df = read_excel_data(excel_path)

    all_results = []
    for i in range(len(race_info_df)):
        race_row = race_info_df.iloc[i]
        label = f"赛事第{i+1}行"
        logger.info(f"--- 预测 {label} ---")

        if len(member_df) == 0:
            logger.error(f"{label} 赛事成绩信息为空，跳过")
            continue

        # 取第一条 finish_time 作为预测输入
        first_finish_time = member_df.iloc[0]['finish_time']
        logger.info(f"{label} 第一条 finish_time: {first_finish_time}")

        # 拼接成模型输入格式
        test_row = build_predict_input(race_row, first_finish_time)

        try:
            # 预测表现分
            y_pred, finish_level = predict_single(test_row, components)
            logger.info(f"{label} | 预测表现分: {y_pred:.2f} | finish_level: {finish_level:.0f}")

            # 计算所有选手成绩
            member_result_df = calculate_all_scores(member_df, y_pred)

            all_results.append(member_result_df)
            logger.info(f"{label} 共计算 {len(member_result_df)} 名选手成绩")
        except Exception as e:
            import traceback
            logger.error(f"{label} 预测失败: {e}\n{traceback.format_exc()}")

    if not all_results:
        logger.error("没有成功的预测结果")
        return None

    # 合并所有结果
    result_df = pd.concat(all_results, ignore_index=True)

    # 输出结果
    if output_path is None:
        output_path = os.path.join(os.path.dirname(excel_path), 'predictions.xlsx')
    result_df.to_excel(output_path, index=False)
    logger.info(f"预测结果已保存到: {output_path}")
    print("\n========== 预测结果 ==========")
    print(result_df.to_string(index=False))
    return result_df


def generate_template(output_path=None):
    """生成空白 Excel 模板（含两个 sheet 页）"""
    if output_path is None:
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'race_template.xlsx')

    # sheet1: 赛事信息
    race_info_data = {
        'race_end_time': ['24:00:00'],
        'aid_station': [5],
        'distance': [50],
        'elevation_gain': [3000],
        'elevation_loss': [2800],
    }
    race_info_df = pd.DataFrame(race_info_data)

    # sheet2: 赛事成绩信息
    member_data = {
        '姓名': ['张三', '李四', '王五'],
        'finish_time': ['06:30:00', '07:15:00', '08:00:00'],
    }
    member_df = pd.DataFrame(member_data)

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        race_info_df.to_excel(writer, sheet_name=SHEET_RACE_INFO, index=False)
        member_df.to_excel(writer, sheet_name=SHEET_MEMBER_RESULT, index=False)

    logger.info(f"Excel 模板已生成: {output_path}")
    logger.info(f"  sheet '{SHEET_RACE_INFO}': race_end_time, aid_station, distance, elevation_gain, elevation_loss")
    logger.info(f"  sheet '{SHEET_MEMBER_RESULT}': 姓名, finish_time")
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TabPFN 表现分预测工具（从 Excel 读取赛事信息）')
    parser.add_argument(
        '--excel', type=str, default=None,
        help='赛事信息 Excel 文件路径（含两个 sheet 页）'
    )
    parser.add_argument(
        '--output', type=str, default=None,
        help='预测结果输出 Excel 路径（默认与输入同目录）'
    )
    parser.add_argument(
        '--model-dir', type=str, default=None,
        help=f'模型保存目录（默认: {DEFAULT_MODEL_DIR}）'
    )
    parser.add_argument(
        '--generate-template', action='store_true',
        help='生成空白 Excel 模板后退出'
    )
    args = parser.parse_args()

    if args.generate_template:
        generate_template()
        sys.exit(0)

    if not args.excel:
        parser.error("请提供 --excel 参数，或使用 --generate-template 生成模版")

    predict_batch(args.excel, model_dir=args.model_dir, output_path=args.output)
