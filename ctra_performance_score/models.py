from sklearn.cluster import KMeans
import numpy as np
import pandas as pd
import os
# from tabpfn import TabPFNRegressor
import numpy as np
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture

# ===================== 纯Python实现K-Medoids（核心） =====================
class SimpleKMedoids:
    def __init__(self, n_clusters=5, metric='euclidean', random_state=42, max_iter=300):
        self.n_clusters = n_clusters    # 簇数量
        self.metric = metric            # 距离度量（仅支持euclidean）
        self.random_state = random_state# 随机种子
        self.max_iter = max_iter        # 最大迭代次数
        self.labels_ = None             # 聚类标签（与sklearn接口对齐）
        self.medoids_ = None            # 最终的medoid点

    # 纯NumPy实现欧氏距离计算（兼容所有NumPy版本）
    def _euclidean_distance(self, X1, X2):
        """
        计算两个数组的欧氏距离矩阵
        X1: (n1, d)，X2: (n2, d) → 输出 (n1, n2)
        """
        # 避免广播维度错误，兼容NumPy 2.x
        X1_expanded = X1[:, np.newaxis, :]  # (n1, 1, d)
        X2_expanded = X2[np.newaxis, :, :]  # (1, n2, d)
        return np.sqrt(np.sum((X1_expanded - X2_expanded) ** 2, axis=-1))

    def fit(self, X):
        """训练K-Medoids模型（输入X为二维数组：(样本数, 特征数)）"""
        np.random.seed(self.random_state)
        n_samples = X.shape[0]
        
        # 1. 初始化：随机选k个点作为初始medoid
        init_indices = np.random.choice(n_samples, self.n_clusters, replace=False)
        self.medoids_ = X[init_indices].copy()

        # 2. 迭代优化
        for _ in range(self.max_iter):
            # 分配簇：每个点分配给最近的medoid
            distances = self._euclidean_distance(X, self.medoids_)
            self.labels_ = np.argmin(distances, axis=1)

            # 更新medoid：每个簇找总距离最小的点
            new_medoids = self.medoids_.copy()
            for i in range(self.n_clusters):
                cluster_points = X[self.labels_ == i]
                if len(cluster_points) == 0:
                    continue  # 空簇跳过
                
                # 计算簇内每个点到其他点的总距离
                cluster_dist = self._euclidean_distance(cluster_points, cluster_points)
                total_dist = np.sum(cluster_dist, axis=1)
                
                # 总距离最小的点作为新medoid
                best_idx = np.argmin(total_dist)
                new_medoids[i] = cluster_points[best_idx]

            # 收敛判断：medoid不再变化则停止
            if np.allclose(self.medoids_, new_medoids):
                break
            self.medoids_ = new_medoids
        return self

# ===================== 原有函数（保持不变） =====================
def dayahead_info_cluster(data):
    # 假设数据为 data，形状为 (300, 96, 8)
    feature_nums = data.shape[-1]
    data_reshaped = data.reshape((-1, feature_nums))

    # 设置聚类的数量
    k = 5  # 根据需要设置聚类数量
    ###kmeans聚类
    kmeans = KMeans(n_clusters=k, init='k-means++', n_init='auto', random_state=42)
    kmeans.fit(data_reshaped)
    # 获取聚类结果
    labels = kmeans.labels_
    ##############
    ###高斯混合聚类
    # gmm = GaussianMixture(n_components=k, random_state=42)
    # gmm.fit(data_reshaped)
    # labels = gmm.predict(data_reshaped)
    ###########################
    last_label = labels[-1]
    indices = np.where(labels == last_label)[0]
    cluster_data = data_reshaped[labels == last_label]
    cluster_data = cluster_data.reshape((-1, feature_nums))
    return cluster_data, indices

# ===================== K-Medoids版本函数（改用纯Python实现） =====================
def dayahead_info_cluster_kmedoids(data):
    """
    K-Medoids聚类函数（与原KMeans版本接口完全一致）
    参数:
        data: 输入数据，形状为 (300, 96, 8)
    返回:
        cluster_data: 最后一个样本所属簇的所有数据，形状 (-1, 8)
        indices: 该簇所有样本在扁平化数组中的索引
    """
    # 数据扁平化（与原逻辑一致）
    feature_nums = data.shape[-1]
    data_reshaped = data.reshape((-1, feature_nums))

    # 设置聚类数量
    k = 5

    # 使用纯Python实现的KMedoids（无任何编译依赖）
    kmedoids = SimpleKMedoids(
        n_clusters=k,
        random_state=42,
        max_iter=300
    )
    kmedoids.fit(data_reshaped)
    labels = kmedoids.labels_

    # 与原逻辑完全一致的结果提取
    last_label = labels[-1]
    indices = np.where(labels == last_label)[0]
    cluster_data = data_reshaped[labels == last_label]
    cluster_data = cluster_data.reshape((-1, feature_nums))

    return cluster_data, indices
def feature_selection(X_train, y_train, corr_threshold=0.2, min_features=5):
    """
    仅使用皮尔逊相关系数筛选特征，保留与目标变量相关性较高的特征
    corr_threshold: 相关系数绝对值阈值
    min_features: 最小保留特征数
    """
    # 1. 计算特征-目标的皮尔逊相关系数
    X_train_df = pd.DataFrame(X_train)
    corr_scores = []
    for col in X_train_df.columns:
        # 计算特征与目标变量的相关系数
        corr = np.corrcoef(X_train_df[col], y_train)[0, 1]
        corr_scores.append(abs(corr))  # 取绝对值
    corr_scores = np.array(corr_scores)

    # 2. 根据阈值筛选特征
    selected_indices = corr_scores >= corr_threshold

    # 3. 确保至少保留min_features个特征
    if np.sum(selected_indices) < min_features:
        # 按相关系数从高到低排序，取前min_features个
        sorted_indices = np.argsort(corr_scores)[::-1]  # 降序排列
        selected_indices = np.zeros_like(corr_scores, dtype=bool)
        selected_indices[sorted_indices[:min_features]] = True

    # 应用筛选
    X_train_selected = X_train[:, selected_indices]
    return X_train_selected, selected_indices
# def train_tabpfn_model_with_params(X_train, y_train,test_data):
#     """
#     使用 TabPFN 训练一个近似的回归模型（通过对连续目标做分箱，然后用 TabPFNClassifier 预测每个箱的概率，再用箱中心的概率加权得到连续预测值）。

#     返回: model, scaler, selected_indices, val_mae
#     注意: 需要安装 tabpfn 包；若未安装会抛出 ImportError，调用方可以捕获并退回到其它模型。
#     """

#     if TabPFNRegressor is not None:
#         try:
#             # 优先使用脚本同目录下的本地 checkpoint（如果存在），以避免 HuggingFace 下载超时
#             script_dir = os.path.dirname(__file__)
#             local_ckpt = os.path.join(script_dir, 'tabpfn-v2-regressor.ckpt')
#             reg_kwargs = {'device': 'cpu', 'random_state': 42,'ignore_pretraining_limits': True } # 新增此行，允许处理超过1000个样本
#             if os.path.exists(local_ckpt):
#                 reg_kwargs['model_path'] = local_ckpt
#             else:
#                 # 保持向后兼容：如果本地不存在则使用默认行为（可能从远程下载）
#                 reg_kwargs['model_path'] = "tabpfn-v2-regressor.ckpt"

#             reg = TabPFNRegressor(**reg_kwargs)
#             reg.fit(X_train, y_train)
#             # 验证集上直接预测连续值
#             y_hat = reg.predict(test_data)
#             return y_hat
#         except Exception as e:
#             tab_model = TabPFNRegressor()
#             tab_model.fit(X_train, y_train)
#             y_hat = tab_model.predict(test_data)
#             return y_hat