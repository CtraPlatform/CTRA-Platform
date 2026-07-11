import pandas as pd
import numpy as np
import copy
import argparse
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
from connect_sql import con_db,operateMysql,operateMysql_multiple
from base_funs import time_to_minute
# from models import dayahead_info_cluster,feature_selection,train_tabpfn_model_with_params,dayahead_info_cluster_kmedoids
from sklearn.preprocessing import StandardScaler
from loguru import logger
from personal_performance_score import calculate_personal_performance_score
def select_data_info(test_distance,test_race_date=None):
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
                and aid_station >0 
                AND a.race_year_id NOT IN (00)
                and a.event_date < '{test_race_date}'
                AND (b.distance + b.elevation_gain / 100) BETWEEN {test_distance} -5 AND {test_distance} + 5
            ORDER BY
                a.event_date,
                a.performance_index'''
    res = operateMysql(sql)
    result = pd.DataFrame(res['data'])
    data = result
    return data
def read_test_data(id):
    selet_test_sql = f'''
                    select
                        dsri.race_date,
                        '1111' as race_year_id,
                        dsmr.finish_time,
                        1000 as performance_index,
                        dsri.race_duration as race_end_time,
                        dsri.aid_station,
                        dsri.distance,
                        dsri.elevation_gain,
                        dsri.elevation_loss * -1 as elevation_loss,
                        dsmr.card
                    from
                        ctra_prod_2024.data_service_race_info dsri
                        left join ctra_prod_2024.data_service_member_race dsmr on dsri.id = dsmr.data_service_race_info_id
                    where
                        dsri.id = {id}
                        and dsmr.finish_status = 1
                    order by 
                        dsmr.finish_time asc
                '''
    res = operateMysql(selet_test_sql)
    if res['msg'] == 'success':
        test_data = res['data']
        test_df = pd.DataFrame(test_data).head(1)
        data_card = pd.DataFrame(test_data)['card'].to_list()
        return test_df,data_card
    else:
        return False
def read_race_member_info(id):
    selet_test_sql = f'''
                    select
                        ranking,
                        finish_time
                    from
                        ctra_prod_2024.data_service_member_race   
                    where
                        data_service_race_info_id = {id}
                    order by ranking asc
                '''
    res = operateMysql(selet_test_sql)
    if res['msg'] == 'success':
        test_data = res['data']
        test_df = pd.DataFrame(test_data)
        return test_df  
    else:
        return False
def read_card_data(card,date,test_distance):
    placeholders = ','.join(['%s'] * len(card))
    select_data_card_sql = f'''
                        SELECT
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
                        LEFT JOIN ctra_prod_2024.data_service_itra_race_info b
                        ON a.race_year_id = b.race_year_id
                        LEFT JOIN ctra_prod_2024.member_base_info m
                        ON a.code = m.code
                        WHERE
                        a.performance_index > 0
                        AND b.aid_station > 0
                        AND a.race_year_id NOT IN (0)
                        AND a.event_date < %s
                        AND m.card in ({placeholders})
                        AND (b.distance + b.elevation_gain / 100) BETWEEN %s - 10 AND %s + 10  -- 简化区间判断
                        ORDER BY
                        a.event_date;
            '''
    params = (date, *card,test_distance,test_distance)
    res = operateMysql(select_data_card_sql, params )
    if res['msg'] == 'success':
        data = res['data']
        data_df = pd.DataFrame(data)
        return data_df
    else:        return pd.DataFrame()
    
def deal_data_info(id):
    test_data,data_card = read_test_data(id)
    test_race_date = test_data['race_date'][0]
    test_distance = test_data['distance'][0] + test_data['elevation_gain'][0]/100
    ##读取前10名参赛者历史比赛数据
    history_data_card = read_card_data(data_card,test_race_date,test_distance)
    logger.info(f"参赛者历史比赛数据{len(history_data_card)}条")

    ##读取参赛者历史比赛数据
    test_data = test_data.drop(['race_date','card'],axis = 1)
    data_df = select_data_info(test_race_date,test_distance)
    logger.info(f"参赛者历史比赛数据{len(data_df)}条")
    # select_data = res['data']
    # data_df = pd.DataFrame(select_data)
    # #添加训练数据
    data_df = pd.concat([data_df,history_data_card])    
    # #添加测试数据
    data_df = pd.concat([history_data_card,test_data])

    #'',用时，表现分，关门时间，补给站，距离，爬升，下降，有效距离
    ##删除nan行
    data_df = data_df.dropna()
    data_df['race_end_time'] = data_df['race_end_time'].apply(time_to_minute)
    data_df['finish_time'] = data_df['finish_time'].apply(time_to_minute)
    # data_df['quality_index'] = data_df['quality_index'].str.extract(r'(\d+)m')[0].astype(int)
    data_df = data_df.astype(float)
    km_effort = data_df['distance'].values  + data_df['elevation_gain'].values/100
    data_df['effort_kilometer'] = km_effort
    aid_stations = data_df['aid_station'].values 
    Penalty_points = []
    Effort_points_final = []
    for i in range(len(km_effort)):
        if aid_stations[i] ==0:
            Penalty_points.append(0)
        else:
            AI = km_effort[i]/aid_stations[i]
            if AI >= 13:
                Penalty_points.append(0)
            elif AI>=11 and AI <13:
                Penalty_points.append(10)
            elif AI>=9 and AI <11:
                Penalty_points.append(15)
            elif AI>=7 and AI <9:
                Penalty_points.append(20)
            elif AI>=5 and AI <7:
                Penalty_points.append(25)
            elif AI <5:
                Penalty_points.append(30)
    Effort_points_final = km_effort - np.array(Penalty_points)
    data_df['Effort_points_final'] = Effort_points_final
    data_df['distance_rate'] =  data_df['finish_time'].values/data_df['distance'].values
    data_df['gain_rate'] =  data_df['finish_time'].values/data_df['elevation_gain'].values
    data_df['epf_rate'] = data_df['finish_time'].values/data_df['Effort_points_final'].values
    data_df['distance_gain_rate'] = data_df['elevation_gain'].values/data_df['distance'].values
    data_df['ekf'] = data_df['effort_kilometer'].values/data_df['finish_time'].values
    data_df = data_df.drop(['race_year_id'],axis = 1)
    return data_df
###预测封装为函数
def forecast_point_fun(id):
    data_df = deal_data_info(id)
    data_info = copy.copy(data_df)
    df_shuffled = data_info
    train_data = copy.copy(df_shuffled)
    # print(train_data.head(5))
    y = train_data['performance_index'].values
    train_data.drop(['performance_index'],axis =1,inplace=True)
    X = train_data.values
    ###对数据进行标准化
    # 创建标准化器
    scaler_X = StandardScaler()
    scaler_y = StandardScaler()
    # 对 X 和 y 分别进行标准化
    X_scaled = scaler_X.fit_transform(X)
    y_scaled = scaler_y.fit_transform(y.reshape(-1, 1)).flatten()
    ##特征选择
    X_train_selected, selected_indices = feature_selection(X_scaled, y_scaled, corr_threshold=0.2, min_features=5)
    # X_train_selected = X_scaled
    ##数据聚类
    # feature_col = [1,2,3,4,6,12]
    data,index = dayahead_info_cluster_kmedoids(X_train_selected)
    index = index.tolist()
    index.sort(reverse=False)
    inpult_data_x, inpult_data_y = X_train_selected[index[:-1]],y_scaled[index[:-1]]
    logger.info(f"同类别数量{len(index)}")
    n = 100  # 请根据实际需求修改这个值
    if len(index) >n:
        # 对 inpult_data_y 从大到小排序，获取排序后的索引
        sorted_indices = np.argsort(-inpult_data_y)  
        top_n_indices = sorted_indices[:n]
        inpult_data_y = inpult_data_y[top_n_indices]
        inpult_data_x = inpult_data_x[top_n_indices]
    # tab_model = TabPFNRegressor()
    # tab_model.fit(inpult_data_x, inpult_data_y)
    # inpult_data_x = X_train_selected[:-1]
    # inpult_data_y = y_scaled[:-1]
    test_data = X_train_selected[-1]

    #选择最优模型
    y_hat = train_tabpfn_model_with_params(inpult_data_x, inpult_data_y,test_data.reshape((1,-1)))
    # y_hat = tab_model.predict(test_data.reshape((1,-1)))
    # y_hat = rf_regressor.predict(test_data)
    y_pred_inv = scaler_y.inverse_transform(y_hat.reshape((1,-1)))
    y_pred = y_pred_inv.tolist()
    y_pred = np.array(y_pred).reshape(-1)
    logger.info(f"赛事{id}表现分预测：{y_pred}")
    ###计算此次赛事的finish_level member_score[i] =  finish_time[i-1] * member_score[i-1]/finish_time[i-1]
    test_info = (data_df.iloc[-1]).astype(float).to_dict()
    # print(f"赛事持续时间: {test_info['race_end_time']}")
    # print(f"第一名用时: {test_info['finish_time']}")
    finish_level = np.ceil(test_info['finish_time'] * y_pred[0]/test_info['race_end_time'])
    logger.info(f"赛事{id}赛事finish_level预测：{finish_level}")
    return  y_pred ,finish_level
def select_member_info(id):
    ###读取参赛选手用时
    select_member_sql = f'''
                    select 
                        id,
                        ranking,
                        finish_time
                    FROM
                        ctra_prod_2024.data_service_member_race x
                    WHERE
                        data_service_race_info_id = {id}
                        and finish_status = 1
                    order BY
                        finish_time
                        '''
    member_info = operateMysql(select_member_sql)
    if member_info['msg'] == 'success':
        member_data = member_info['data']
        member_df = pd.DataFrame(member_data)
        member_df['finish_time'] = member_df['finish_time'].apply(time_to_minute)
        return member_df
    else:
        return False
def Calculate_performance_score(race_member_info,y_pred):
    member_score = np.zeros((len(race_member_info)))
    member_score[0] = y_pred[0]
    finish_time = race_member_info['finish_time'].values
    for i in range(1,len(race_member_info)):
       member_score[i] =  finish_time[i-1] * member_score[i-1]/finish_time[i]
    return member_score
## 结果插入数据库
def save_score_info(race_member_info):
    data_arr = []
    save_sql = f'''
                 update ctra_prod_2024.data_service_member_race set ctra_performance_index = %s where id = %s
                '''
    for i in range(len(race_member_info)):
        data_arr.append([race_member_info.iloc[i]['member_performance_score'],race_member_info.iloc[i]['id']])
    result = operateMysql_multiple(save_sql, data_arr)
    if result['msg'] == 'success':
        logger.info(f"ctra表现分更新成功")
    else:
        error_info = f" ctra表现分更新失败, {result['error']}"
        logger.error(error_info)
        assert 0, error_info
###更新赛事finish_level
def update_finish_level(race_id, finish_level):
    update_sql = f'''
                 update ctra_prod_2024.data_service_race_info set ctra_finisher_level = {finish_level} where id = {race_id} 
                '''
    result = operateMysql(update_sql)
    if result['msg'] == 'success':
        logger.info(f"finish_level更新成功")
    else:
        error_info = f"finish_level更新失败, {result['error']}"
        logger.error(error_info)
        assert 0, error_info
def process_single_race(race_id):
    """处理单个赛事"""
    y_pred, finish_level = forecast_point_fun(race_id)
    logger.info(f"赛事{race_id}预测完成，开始更新数据库")
    race_member_info = select_member_info(race_id)
    logger.info(f"赛事{race_id},选手信息读取完成，开始计算表现分")
    member_performance_score = Calculate_performance_score(race_member_info, y_pred)
    logger.info(f"赛事{race_id},表现分计算完成，开始保存表现分")
    race_member_info['member_performance_score'] = member_performance_score
    save_score_info(race_member_info)
    logger.info(f"赛事{race_id},保存表现分完成，开始更新finish_level")
    ###finish_level 写入赛事信息表
    update_finish_level(race_id, finish_level)
    logger.info(f"赛事{race_id},保存表现分完成")
    # calculate_personal_performance_score([race_id])
    # logger.info(f"赛事{race_id},所有更新完成")
    return True

def main_sequential(id_list):
    """顺序处理版本"""
    for id in id_list:
        y_pred,finish_level = forecast_point_fun(id)
        race_member_info = select_member_info(id)
        member_performance_score = Calculate_performance_score(race_member_info, y_pred)
        race_member_info['member_performance_score'] = member_performance_score
        logger.info(race_member_info.head(20))
        # save_score_info(race_member_info)
        # ###finish_level 写入赛事信息表
        # update_finish_level(id, finish_level)
        # logger.info(f"赛事{id}表现分更新完成")
        # logger.info(f"开始计算赛事{id}用户综合表现分")
        # calculate_personal_performance_score(id)
def select_id_list():
    """查询需要处理的赛事ID列表"""
    sql = '''
        select DISTINCT
        id
        from
        ctra_prod_2024.`data_service_race_info`
        order by
        id desc 
    '''
    res = operateMysql(sql)
    if res['msg'] == 'success':
        id_data = res['data']
        id_df = pd.DataFrame(id_data)
        id_list = id_df['id'].tolist()
        return id_list
    else:
        logger.error(f"查询赛事ID失败: {res['error']}")
        return []
import sys
if __name__ == '__main__':
    # ====== 读取赛事ID列表 ======
    id_list = [3]
    main_sequential(id_list)




    # ###读取赛事id列表
    # id_list = select_id_list()    
    # # ====== 关键修改：使用argparse替代input() ======
    # parser = argparse.ArgumentParser(description='赛事表现分计算工具')
    # if not id_list:
    #     parser.add_argument('--ids', type=str, required=True,
    #                     help='赛事ID列表，逗号分隔（如：1,2,3）')
    # else:
    #     default_ids = ','.join(map(str, id_list))
    #     #分批次处理赛事，避免一次性处理过多赛事导致资源占用过高
    #     for i in range(0, len(id_list), 50):
    #         batch_ids = id_list[i:i+50]
    #         logger.info(f"处理赛事ID批次: {batch_ids}")

    #     parser.add_argument('--ids', type=str, default=default_ids,
    #                     help=f'赛事ID列表，逗号分隔（如：1,2,3），默认为数据库查询结果: {default_ids}')
    # parser.add_argument('--use-multiprocessing', action='store_true',
    #                     help='使用多进程（默认启用）')
    # parser.add_argument('--max-workers', type=int,
    #                     help='最大工作进程数（默认为CPU核心数）')
    
    # args = parser.parse_args()
    
    # # 解析ID列表
    # id_list = list(map(int, args.ids.split(',')))
    # # logger.basicConfig(level=logger.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # logger.info(f"输入的赛事ID: {id_list}")
    
    # if args.use_multiprocessing:
    #     logger.info("使用多进程处理模式")
    #     main(id_list, args.max_workers)
    # else:
    #     logger.info("使用顺序处理模式")
    #     main_sequential(id_list)
