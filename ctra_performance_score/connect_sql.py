import pymysql as ps
def con_db():
    return ps.connect(
        host='mysql地址',  # 地址
        port=端口,
        user='你的用户名',  # 用户名
        password='你的密码',  # 密码
        database='数据库名',
        charset='utf8',
    )
def operateMysql(sql,param=None):
    result = {}
    try:
        with con_db() as conn:
            # sql = ("SELECT machine_code,machine_desc FROM vpp_gateway")
            with conn.cursor() as cursor:
                # 执行sql语句
                cursor.execute(sql,param)
                result['msg'] = 'success'
                if 'select' in sql.casefold():
                    #得到结果
                    rows = cursor.fetchall()
                    #将结果转化为字典格式
                    data = []
                    for row in rows:
                        dict1 = {col[0]: row[i] for i, col in enumerate(cursor.description)}
                        data.append(dict1)
                    result['data']= data
                else:
                    conn.commit()
                return result
    except Exception as e:
        result['msg'] = 'fail'
        result['error'] = f"发生了一个错误：{e}"
        return result
def operateMysql_multiple(sql,data):
    '''
    :param sql:sql语句
    :param data:要操作的数据
    :return:
    '''
    result = {}
    try:
        with con_db() as conn:
            with conn.cursor() as cursor:
                # 执行sql语句
                cursor.executemany(sql,data)
                result['msg'] = 'success'
                conn.commit()
                return result
    except Exception as e:
        result['msg'] = 'fail'
        result['error'] = f"发生了一个错误：{e}"
        return result