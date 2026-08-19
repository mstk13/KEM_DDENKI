"""ローカル埋め込みモデル（Ollama / bge-m3）のクライアント。

ADR-0010「AI推論の3層分割」の層Aにあたる。
品目名をベクトル化し、コサイン類似度で候補を絞り込む。

設計上の前提:
- Ollama はホスト側で稼働し、コンテナからは host.docker.internal:11434 で到達する
- **埋め込み単体では確定判断をしない。** 実測で、同一品目の略記(0.768)と
  別種ケーブル(0.668)の類似度差が 0.10 しかないことを確認済み。
  高信頼帯のみ自動確定し、中間帯は LLM に候補を渡して判断させる
- 到達不可・タイムアウト時は例外を投げず None を返す。呼び出し側は
  従来のカスケード（LLM マッチング）にフォールバックする

依存追加はしない。stdlib の urllib で足りる。
"""

import json
import logging
import math
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

# 実測に基づく閾値（docs/saas/design/local-inference-runbook.html 参照）
#   0.85 以上 … 自動確定
#   0.65〜0.85 … LLM に候補を渡して判断させる
#   0.65 未満 … 不一致
AUTO_CONFIRM_THRESHOLD = 0.85
CANDIDATE_THRESHOLD = 0.65


def _base_url() -> str:
    return getattr(
        settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
    ).rstrip("/")


def _model() -> str:
    return getattr(settings, "OLLAMA_EMBED_MODEL", "bge-m3")


def _timeout() -> int:
    return int(getattr(settings, "OLLAMA_EMBED_TIMEOUT", 60))


def _keep_alive() -> str:
    """モデルをVRAMに常駐させる時間。

    ホスト側に OLLAMA_KEEP_ALIVE=0 が設定されているため、指定しないと
    1リクエストごとにアンロードされ、次回に再ロードが丸ごと乗る。
    実測でコールド 3.3秒 / ウォーム 0.27秒 と約12倍の差がある。
    リクエストの keep_alive はサーバ側の環境変数を上書きするので、
    ホストの設定に手を入れずにここで打ち消せる。
    """
    return str(getattr(settings, "OLLAMA_KEEP_ALIVE", "5m"))


def is_configured() -> bool:
    """埋め込み機能が有効化されているか。"""
    return bool(getattr(settings, "OLLAMA_EMBED_ENABLED", True)) and bool(_base_url())


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """複数テキストを一括でベクトル化する。

    実測で1件あたり約220ms かかるため、必ずまとめて渡すこと。
    1件ずつ呼ぶと件数分そのまま遅くなる。

    Returns:
        埋め込みベクトルのリスト。失敗時は None（例外は投げない）。
    """
    if not texts or not is_configured():
        return None

    payload = json.dumps(
        {"model": _model(), "input": texts, "keep_alive": _keep_alive()},
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{_base_url()}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        # 到達不可でも例外は投げない。呼び出し側はLLMマッチングへ落ちる。
        logger.warning("埋め込み取得に失敗しました（LLMへフォールバック）: %s", e)
        return None

    vectors = data.get("embeddings")
    if not vectors or len(vectors) != len(texts):
        logger.warning(
            "埋め込みの件数が一致しません: 要求 %d / 応答 %s",
            len(texts),
            len(vectors) if vectors else 0,
        )
        return None
    return vectors


def embed_text(text: str) -> list[float] | None:
    """単一テキストをベクトル化する。"""
    vectors = embed_texts([text])
    return vectors[0] if vectors else None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """コサイン類似度。numpy が使えればそちらを使う。

    numpy は scikit-learn 経由で必ず入っているが、
    入っていない環境でも動くように純Python版を残す。
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    try:
        import numpy as np

        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        return float(np.dot(va, vb) / denom) if denom else 0.0
    except ImportError:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0


def rank_by_similarity(
    query_vector: list[float],
    candidates: list[tuple[object, list[float]]],
    *,
    top_k: int = 5,
    min_score: float = CANDIDATE_THRESHOLD,
) -> list[tuple[object, float]]:
    """候補をコサイン類似度で並べ替え、上位 top_k 件を返す。

    Args:
        query_vector: 照合対象のベクトル
        candidates: (任意のオブジェクト, ベクトル) のリスト
        top_k: 返す件数
        min_score: この値未満は捨てる

    Returns:
        (オブジェクト, スコア) の降順リスト
    """
    if not query_vector or not candidates:
        return []

    try:
        import numpy as np

        objs = [obj for obj, vec in candidates if vec]
        mat = np.asarray([vec for _obj, vec in candidates if vec], dtype=np.float32)
        if mat.size == 0:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1) * float(np.linalg.norm(q))
        # ゼロ除算を避ける
        norms[norms == 0] = 1e-9
        scores = (mat @ q) / norms
        ranked = sorted(
            zip(objs, (float(s) for s in scores), strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
    except ImportError:
        ranked = sorted(
            (
                (obj, cosine_similarity(query_vector, vec))
                for obj, vec in candidates
                if vec
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )

    return [(obj, score) for obj, score in ranked if score >= min_score][:top_k]
