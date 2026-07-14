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
    └── performance_model_info.pkl        # 元信息
```

## 环境依赖

```bash
pip install -r requirements.txt
```

> TabPFN 的模型 checkpoint `tabpfn-v2-regressor.ckpt` 位于上级目录 `ctra_performance_score/` 中。

### 第二步：准备 Excel 赛事信息

### 第三步：预测

```bash
# 基本用法
python predict_from_excel.py --excel races.xlsx

# 指定输出路径
python predict_from_excel.py --excel races.xlsx --output predictions.xlsx
```

预测结果会输出到控制台并保存为 Excel 文件。
