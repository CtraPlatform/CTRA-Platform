# CTRA Performance Score

本目录用于计算 CTRA 赛事表现分、赛事完赛等级以及用户综合表现分。主入口为 `tabpfn_ctra_new.py`，核心思路是：从历史赛事中筛选与待计算赛事相似的样本，使用 TabPFN 回归模型预测该赛事第一名表现分，再按完赛时间比例递推每位完赛选手的赛事表现分，最后更新赛事和用户维度的数据库字段。
TabPFN（Tabular Prior-data Fitted Network）基于Transformer架构与贝叶斯先验拟合思想，模型核心原理为近似贝叶斯后验预测分布。预训练阶段，模型在海量多样化合成表格数据集学习通用数据分布规律，习得表格数据的特征交互、数值映射通用先验知识，替代传统模型的单任务训练流程。
推理阶段采用全局上下文建模方式，通过双向注意力机制，既捕捉单样本内部特征关联，也挖掘全量样本间的数据分布规律。模型将训练集作为上下文支持集、测试样本作为查询集，经多层Transformer完成特征交互编码，最终通过回归专用输出头，输出目标值的连续概率分布，不仅输出单点预测值，还可量化预测不确定性。
## 目录说明

| 文件 | 作用 |
| --- | --- |
| `tabpfn_ctra_new.py` | 主函数入口，负责赛事数据读取、特征构造、模型预测、成绩写库和批处理调度 |
| `models.py` | 特征选择、KMeans 聚类、K-Medoids 备用实现、TabPFN 预测函数位置 |
| `base_funs.py` | 时间格式转换工具 |
| `connect_sql.py` | MySQL 连接和查询/写入封装 |
| `personal_performance_score.py` | 根据近 36 个月赛事表现分计算用户综合表现分 |
| `online_flask.py` | Flask 触发接口 |
| `requirements.txt` | Python 依赖 |
| `dockerfile` | 容器运行配置 |

## 模型算法原理

### 1. 数据来源

`tabpfn_ctra_new.py` 以赛事 ID 为输入，先读取待计算赛事第一名成绩和赛道信息，再读取该赛事日期之前的历史 ITRA/CTRA 赛事数据作为训练样本。

训练样本主要字段包括：

- `finish_time`：第一名完赛时间
- `performance_index`：历史赛事第一名表现分
- `race_end_time`：赛事关门时间
- `aid_station`：补给站数量
- `distance`：赛事距离
- `elevation_gain`：累计爬升
- `elevation_loss`：累计下降

待计算赛事会被拼接到历史样本最后一行。后续流程默认最后一行就是预测样本。

### 2. 特征工程

代码先将 `finish_time` 和 `race_end_time` 从 `HH:MM:SS` 转成分钟，再将数据转为数值型。

核心构造特征如下：

```text
effort_kilometer = distance + elevation_gain / 100
```

`effort_kilometer` 表示考虑爬升后的有效距离。随后根据每个补给站覆盖的有效距离计算补给密度惩罚：

```text
AI = effort_kilometer / aid_station
```

补给站越密集，惩罚越高：

| AI 区间 | 惩罚分 |
| --- | --- |
| AI >= 13 | 0 |
| 11 <= AI < 13 | 10 |
| 9 <= AI < 11 | 15 |
| 7 <= AI < 9 | 20 |
| 5 <= AI < 7 | 25 |
| AI < 5 | 30 |

最终有效强度分：

```text
Effort_points_final = effort_kilometer - Penalty_points
```

再派生时间、距离、爬升相关比率：

```text
distance_rate = finish_time / distance
gain_rate = finish_time / elevation_gain
epf_rate = finish_time / Effort_points_final
distance_gain_rate = elevation_gain / distance
ekf = effort_kilometer / finish_time
```

这些特征共同描述赛事距离、爬升、补给密度、冠军速度和赛道强度。

### 3. 标准化

模型训练前分别对特征 `X` 和目标 `y = performance_index` 做标准化：

```text
X_scaled = StandardScaler().fit_transform(X)
y_scaled = StandardScaler().fit_transform(y)
```

预测完成后再通过 `scaler_y.inverse_transform` 还原到原始表现分尺度。

### 4. 特征选择

`models.feature_selection` 使用皮尔逊相关系数筛选特征：

```text
corr(feature_i, y)
```

默认保留绝对相关系数不小于 `0.2` 的特征。如果满足阈值的特征数量少于 `5`，则按相关性从高到低至少保留前 `5` 个特征。

这一步用于减少弱相关特征对小样本回归的干扰。

### 5. 相似赛事聚类

`models.dayahead_info_cluster` 对筛选后的全部样本做 KMeans 聚类：

```text
k = 5
labels = KMeans(n_clusters=5).fit_predict(X_selected)
```

由于待计算赛事位于最后一行，代码取最后一行所属簇，并只保留同簇历史样本作为 TabPFN 的上下文训练样本：

```text
last_label = labels[-1]
indices = where(labels == last_label)
train_context = same_cluster_samples_excluding_last_row
```

如果同簇样本超过 `100` 条，会按历史表现分从高到低保留前 `100` 条，控制 TabPFN 输入规模。

### 6. TabPFN 回归预测

TabPFN 是面向表格数据的小样本先验模型。当前流程将相似赛事样本作为上下文：

```text
X_context = 同簇历史赛事特征
y_context = 同簇历史赛事表现分
X_test = 待计算赛事特征
```

再调用：

```python
y_hat = train_tabpfn_model_with_params(X_context, y_context, X_test)
```

输出待计算赛事第一名的预测表现分 `y_pred`。

当前代码期望使用本目录下的 `tabpfn-v2-regressor.ckpt` 作为本地模型权重，避免运行时从远端下载模型。

### 7. 赛事完赛等级

预测第一名表现分后，代码计算赛事 `finish_level`：

```text
finish_level = ceil(first_finish_time * predicted_winner_score / race_end_time)
```

其中：

- `first_finish_time`：第一名完赛时间，单位分钟
- `predicted_winner_score`：模型预测的第一名表现分
- `race_end_time`：赛事关门时间，单位分钟

结果写入 `data_service_race_info.ctra_finisher_level`。

### 8. 选手表现分递推

第一名选手表现分等于模型预测值：

```text
score_0 = y_pred
```

其余选手按相邻名次完赛时间比例递推：

```text
score_i = finish_time_(i-1) * score_(i-1) / finish_time_i
```

完赛时间越长，表现分越低。结果写入 `data_service_member_race.ctra_performance_index`。

### 9. 用户综合表现分

赛事表现分更新完成后，`calculate_personal_performance_score` 会基于用户近 36 个月内的赛事表现分计算综合表现分：

1. 读取本批赛事涉及用户的历史成绩。
2. 按表现分从高到低取前 5 场。
3. 根据成绩距今月份衰减权重：

| 距今月份 | 权重 |
| --- | --- |
| 0-11 | 1 |
| 12-17 | 0.995 |
| 18-23 | 0.99 |
| 24-29 | 0.985 |
| 30-35 | 0.98 |
| >= 36 | 0 |

4. 对前 1-5 场成绩应用组合权重，取所有组合均值中的最大值作为用户综合表现分。
5. 更新 `data_service_member_info.ctra_performance_index`。

## 运行前检查

1. 确认可以访问 `connect_sql.py` 中配置的 MySQL 数据库。
2. 确认本目录存在 `tabpfn-v2-regressor.ckpt`。
3. 安装依赖：

```bash
cd ctra_performance_score
pip install -r requirements.txt
```

4. 注意当前 `models.py` 中 `train_tabpfn_model_with_params` 的定义和 `TabPFNRegressor` 导入处于注释状态，而 `tabpfn_ctra_new.py` 会直接导入该函数。若直接运行时报如下错误：

```text
ImportError: cannot import name 'train_tabpfn_model_with_params' from 'models'
```

需要先恢复 `models.py` 中 TabPFN 相关导入和 `train_tabpfn_model_with_params` 函数定义。

## 命令行运行

进入目录：

```bash
cd ctra_performance_score
```

按指定赛事 ID 顺序处理：

```bash
python tabpfn_ctra_new.py --ids 1,2,3
```

启用多进程：

```bash
python tabpfn_ctra_new.py --ids 1,2,3 --use-multiprocessing --max-workers 8
```

设置批次大小：

```bash
python tabpfn_ctra_new.py --ids 1,2,3,4,5 --batch-size 50
```

参数说明：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--ids` | 赛事 ID 列表，使用英文逗号分隔 | 若数据库查询到赛事 ID，则默认使用查询结果；否则必填 |
| `--use-multiprocessing` | 是否启用多进程处理赛事 | 默认关闭，顺序处理 |
| `--max-workers` | 最大进程数 | `min(赛事数, CPU核心数)` |
| `--batch-size` | 每批处理赛事数量 | `50` |

## Docker 运行

构建镜像：

```bash
cd ctra_performance_score
docker build -f dockerfile -t ctra-performance-score .
```

运行默认命令：

```bash
docker run --rm ctra-performance-score
```

覆盖默认赛事参数：

```bash
docker run --rm ctra-performance-score python /app/tabpfn_ctra_new.py --ids 1,2,3 --use-multiprocessing --max-workers 8
```

## Flask 触发

`online_flask.py` 提供 `/trigger` 接口，默认监听 `0.0.0.0:8090`。

启动服务：

```bash
cd ctra_performance_score
python online_flask.py
```

GET 请求示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" "http://127.0.0.1:8090/trigger?ids=1&ids=2"
```

POST JSON 请求示例：

```bash
curl -X POST "http://127.0.0.1:8090/trigger" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"ids":["1","2","3"]}'
```

## 输出结果

主流程会更新以下字段：

| 表 | 字段 | 含义 |
| --- | --- | --- |
| `data_service_member_race` | `ctra_performance_index` | 单场赛事选手表现分 |
| `data_service_race_info` | `ctra_finisher_level` | 赛事完赛等级 |
| `data_service_member_info` | `ctra_performance_index` | 用户综合表现分 |

日志通过 `loguru` 输出，包含每个赛事的预测表现分、完赛等级、写库状态、批次成功/失败数量等信息。
