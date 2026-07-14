# TabPFN 表现分模型 - 训练与预测流程

基于 `tabpfn_ctra_new.py` 的 `select_data_info` 和 `forecast_point_fun` 逻辑，将训练与预测拆分为独立步骤。

## 目录结构

```
model_pipeline/
├── feature_engineering.py   # 特征工程公共模块（从 deal_data_info 提取）
├── train_model.py           # 训练脚本：读取数据 → 特征工程 → 标准化 → 特征选择 → 保存
├── predict_from_excel.py    # 预测脚本：读取Excel → 加载模型 → 聚类 → TabPFN预测 → 输出
├── README.md                # 本文件
└── saved_model/             # 训练后自动生成
    ├── train_df.pkl          # 特征工程后的训练数据
    ├── scaler_X.pkl          # X 标准化器
    ├── scaler_y.pkl          # y 标准化器
    ├── selected_indices.pkl  # 特征选择索引
    └── model_info.pkl        # 元信息
```

## 环境依赖

```bash
pip install tabpfn scikit-learn pandas numpy openpyxl loguru pymysql
```

> TabPFN 的模型 checkpoint `tabpfn-v2-regressor.ckpt` 位于上级目录 `ctra_performance_score/` 中。

## 使用方法

### 第一步：训练模型并保存

```bash
# 使用默认截止日期 2026-07-01
python train_model.py

# 自定义截止日期和保存目录
python train_model.py --cutoff-date 2026-07-01 --output-dir ./saved_model
```

训练完成后，`saved_model/` 目录下会生成 5 个 `.pkl` 文件。

### 第二步：准备 Excel 赛事信息

生成空白模板：

```bash
python predict_from_excel.py --generate-template
```

模板格式（`race_template.xlsx`）：

| race_name | finish_time | race_end_time | aid_station | distance | elevation_gain | elevation_loss |
|-----------|-------------|---------------|-------------|----------|----------------|----------------|
| 示例赛事  | 06:30:00    | 24:00:00      | 5           | 50       | 3000           | 2800           |

**列说明：**

| 列名 | 类型 | 说明 |
|------|------|------|
| race_name | 文本（可选） | 赛事名称，仅用于标识 |
| finish_time | 字符串 HH:MM:SS | 第一名用时 |
| race_end_time | 字符串 HH:MM:00 | 关门时间 |
| aid_station | 整数 | 补给站数量 |
| distance | 数值 | 距离 (km) |
| elevation_gain | 数值 | 爬升 (m) |
| elevation_loss | 数值 | 下降 (m，正数) |

### 第三步：预测

```bash
# 基本用法
python predict_from_excel.py --excel races.xlsx

# 指定输出路径
python predict_from_excel.py --excel races.xlsx --output predictions.xlsx
```

预测结果会输出到控制台并保存为 Excel 文件。

## 原理说明

TabPFN 属于 in-context learning 模型，其"训练"本质是存储训练数据，"预测"时将训练数据作为上下文进行推理。因此：

- **训练阶段**保存的是：训练数据（特征工程后）、标准化器、特征选择索引
- **预测阶段**流程：
  1. 加载训练数据和预处理器
  2. 读取 Excel 赛事信息，做特征工程
  3. 合并训练数据和测试数据
  4. 用保存的 scaler 标准化
  5. 用保存的 selected_indices 选择特征
  6. KMeans 聚类，选择与测试数据同类的训练样本
  7. 取表现分最高的 100 个样本
  8. TabPFN 预测，反标准化得到表现分
  9. 计算 finish_level = ceil(finish_time × 表现分 / race_end_time)

与原 `forecast_point_fun` 的区别：标准化器和特征选择索引在训练阶段一次性 fit 并保存，预测时直接加载使用，避免每次预测重复计算。
