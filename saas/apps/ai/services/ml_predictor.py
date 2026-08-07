"""LightGBM によるコスト予測サービス。

完工済み現場の実績データを学習し、施工中現場の最終原価を予測する。
予算超過確率・特徴量重要度も算出し、原価管理の意思決定を支援する。
"""

import json
import logging
import time
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from apps.ai.models import AILog
from apps.ai.services.data_collector import collect_site_cost_features
from apps.sites.models import Site

logger = logging.getLogger(__name__)

# LightGBM はオプショナル依存（CI等で未インストールの場合がある）
try:
    import numpy as np
    import lightgbm as lgb
    from sklearn.model_selection import cross_val_predict

    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

# joblib はモデルの保存/読み込みに使用
try:
    import joblib

    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

# 学習に必要な最小現場数
MIN_TRAINING_SAMPLES = 5

# 特徴量のうち、モデル入力に使うカラム（原価区分比率は動的に追加）
BASE_FEATURE_KEYS = [
    "contract_amount",
    "duration_days",
    "elapsed_days",
    "elapsed_ratio",
    "budget_total",
    "budget_item_count",
    "cost_total",
    "cost_transaction_count",
    "consumption_ratio",
    "daily_burn",
    "recent_daily_burn",
    "burn_acceleration",
    "total_work_hours",
    "overtime_ratio",
    "worker_count",
    "report_count",
    "process_count",
    "delay_ratio",
]


class CostPredictor:
    """完工時の最終原価を予測する LightGBM モデル。"""

    MODEL_DIR = Path(getattr(settings, "BASE_DIR", ".")) / "ml_models"

    def __init__(self):
        if not HAS_LGBM:
            raise ImportError(
                "lightgbm がインストールされていません。"
                "pip install lightgbm scikit-learn でインストールしてください。"
            )
        if not HAS_JOBLIB:
            raise ImportError(
                "joblib がインストールされていません。"
                "pip install joblib でインストールしてください。"
            )

    def train(self, company):
        """完工済み現場のデータで学習する。

        Args:
            company: テナント（Company インスタンス）

        Returns:
            dict: 学習結果の概要。学習データ不足の場合は警告を含む。
        """
        # 完工済み / 請求済みの現場を収集（unscoped: 全テナント横断ではなく company で絞り込み）
        completed_sites = Site.unscoped.filter(
            company=company,
            status__in=[Site.Status.COMPLETED, Site.Status.BILLED],
        )

        if completed_sites.count() < MIN_TRAINING_SAMPLES:
            msg = (
                f"学習データが不足しています（{completed_sites.count()}件 / "
                f"最低{MIN_TRAINING_SAMPLES}件必要）。"
            )
            logger.warning(msg)
            return {"status": "insufficient_data", "message": msg}

        # 特徴量と目的変数を収集
        features_list = []
        targets = []
        feature_keys = None

        for site in completed_sites:
            features = collect_site_cost_features(site)
            if features["budget_total"] <= 0:
                continue  # 予算未設定の現場はスキップ

            # 完工時の最終消化率を目的変数とする
            final_ratio = features["cost_total"] / features["budget_total"]
            targets.append(final_ratio)

            # 特徴量キーを統一（初回で決定）
            if feature_keys is None:
                feature_keys = sorted(features.keys())
            row = [features.get(k, 0.0) for k in feature_keys]
            features_list.append(row)

        if len(features_list) < MIN_TRAINING_SAMPLES:
            msg = (
                f"有効な学習データが不足しています（{len(features_list)}件 / "
                f"最低{MIN_TRAINING_SAMPLES}件必要）。"
            )
            logger.warning(msg)
            return {"status": "insufficient_data", "message": msg}

        X = np.array(features_list)
        y = np.array(targets)

        # LightGBM パラメータ（少データ向けに保守的な設定）
        params = {
            "objective": "regression",
            "metric": "rmse",
            "n_estimators": 100,
            "max_depth": 4,
            "num_leaves": 15,
            "learning_rate": 0.05,
            "min_child_samples": 2,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "verbose": -1,
            "random_state": 42,
        }

        # クロスバリデーション（overrun_probability 推定のためのばらつき取得）
        n_splits = min(5, len(X))
        if n_splits >= 2:
            cv_predictions = cross_val_predict(
                lgb.LGBMRegressor(**params),
                X,
                y,
                cv=n_splits,
            )
            cv_residuals_std = float(np.std(y - cv_predictions))
        else:
            cv_residuals_std = 0.1  # デフォルト

        # 全データで学習
        model = lgb.LGBMRegressor(**params)
        model.fit(X, y)

        # モデルを保存
        self.MODEL_DIR.mkdir(parents=True, exist_ok=True)
        model_path = self.MODEL_DIR / f"{company.pk}_cost_model.joblib"
        model_data = {
            "model": model,
            "feature_keys": feature_keys,
            "cv_residuals_std": cv_residuals_std,
            "n_samples": len(X),
            "company_pk": company.pk,
        }
        joblib.dump(model_data, model_path)

        logger.info(
            "コスト予測モデルを学習しました: company=%s, samples=%d, path=%s",
            company.name,
            len(X),
            model_path,
        )

        return {
            "status": "success",
            "n_samples": len(X),
            "cv_residuals_std": cv_residuals_std,
            "model_path": str(model_path),
        }

    def predict(self, site, user=None):
        """現場の最終原価を予測する。

        Args:
            site: 予測対象の Site インスタンス
            user: 実行ユーザー（AILog 記録用、省略可）

        Returns:
            dict | None: 予測結果。モデル未学習の場合は None。
        """
        start_time = time.time()

        model_data = self._load_model(site.company)
        if model_data is None:
            return None

        model = model_data["model"]
        feature_keys = model_data["feature_keys"]
        cv_residuals_std = model_data["cv_residuals_std"]

        # 特徴量を収集
        features = collect_site_cost_features(site)
        row = [features.get(k, 0.0) for k in feature_keys]
        X = np.array([row])

        # 予測
        predicted_ratio = float(model.predict(X)[0])

        # 予測最終原価（budget_total * predicted_ratio）
        budget_total = Decimal(str(features["budget_total"]))
        if budget_total > 0:
            predicted_final_cost = budget_total * Decimal(str(predicted_ratio))
            # 1円未満を四捨五入
            predicted_final_cost = predicted_final_cost.quantize(Decimal("1"))
        else:
            predicted_final_cost = Decimal("0")

        # 予算超過確率（予測消化率が100%を超える確率）
        # 正規分布近似：P(ratio > 1.0) を残差の標準偏差から推定
        if cv_residuals_std > 0:
            z_score = (1.0 - predicted_ratio) / cv_residuals_std
            # 標準正規分布の上側確率を近似計算
            overrun_probability = float(self._normal_sf(z_score))
        else:
            overrun_probability = 1.0 if predicted_ratio >= 1.0 else 0.0

        overrun_probability = max(0.0, min(1.0, overrun_probability))

        # 信頼度の判定
        n_samples = model_data.get("n_samples", 0)
        if n_samples >= 30 and cv_residuals_std < 0.1:
            confidence = "high"
        elif n_samples >= 10 and cv_residuals_std < 0.2:
            confidence = "medium"
        else:
            confidence = "low"

        # 特徴量重要度トップ5
        importances = model.feature_importances_
        top_indices = np.argsort(importances)[::-1][:5]
        feature_importance = {
            feature_keys[i]: float(importances[i])
            for i in top_indices
            if importances[i] > 0
        }

        latency_ms = int((time.time() - start_time) * 1000)

        result = {
            "predicted_final_cost": predicted_final_cost,
            "predicted_consumption_ratio": predicted_ratio,
            "overrun_probability": overrun_probability,
            "confidence": confidence,
            "feature_importance": feature_importance,
        }

        # AILog に記録
        try:
            AILog.unscoped.create(
                company=site.company,
                site=site,
                task_type=AILog.TaskType.COST_FORECAST,
                model_used=AILog.ModelType.LGBM,
                model_version=f"lgbm_cost_v1_n{n_samples}",
                input_data=features,
                prompt="",  # ML系はプロンプト無し
                response=json.dumps(
                    {
                        k: str(v) if isinstance(v, Decimal) else v
                        for k, v in result.items()
                    },
                    ensure_ascii=False,
                ),
                response_parsed={
                    k: str(v) if isinstance(v, Decimal) else v
                    for k, v in result.items()
                },
                status=AILog.Status.SUCCESS,
                latency_ms=latency_ms,
                cost_usd=Decimal("0"),  # ローカル推論のためAPI費用なし
                requested_by=user,
            )
        except Exception:
            logger.exception("AILog の記録に失敗しました")

        return result

    def _load_model(self, company):
        """保存済みモデルを読み込む。なければ None。"""
        model_path = self.MODEL_DIR / f"{company.pk}_cost_model.joblib"
        if not model_path.exists():
            logger.info(
                "モデルファイルが見つかりません: %s（先に train を実行してください）",
                model_path,
            )
            return None
        try:
            return joblib.load(model_path)
        except Exception:
            logger.exception("モデルの読み込みに失敗しました: %s", model_path)
            return None

    @staticmethod
    def _normal_sf(z):
        """標準正規分布の上側確率（survival function）の近似。

        scipy に依存しないよう、Abramowitz & Stegun の近似式を使用。
        """
        import math

        if z < -6:
            return 1.0
        if z > 6:
            return 0.0

        # 累積分布関数の近似
        a1 = 0.254829592
        a2 = -0.284496736
        a3 = 1.421413741
        a4 = -1.453152027
        a5 = 1.061405429
        p = 0.3275911

        sign = 1.0 if z >= 0 else -1.0
        x = abs(z) / math.sqrt(2.0)
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (
            ((((a5 * t + a4) * t) + a3) * t + a2) * t + a1
        ) * t * math.exp(-x * x)

        cdf = 0.5 * (1.0 + sign * y)
        return 1.0 - cdf
