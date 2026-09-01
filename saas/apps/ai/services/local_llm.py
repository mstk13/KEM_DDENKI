"""ローカル生成モデル（Ollama / qwen3:8b）のクライアント。

ADR-0010「AI推論の3層分割」の層Bにあたる。
`embedding.py`（層A）と同じ方針で、依存追加はせず stdlib の urllib で足りる。

設計上の前提:
- Ollama はホスト側で稼働し、コンテナからは host.docker.internal:11434 で到達する
- **必ず JSON Schema を渡す。** `format` に文字列 "json" を指定するだけでは
  キー名も構造も守られない出力になる。Schema オブジェクトを渡すと構造・キー名・
  型がすべて守られ、副次的に出力トークンが 1,550→111、所要が 27秒→2秒に減る
- 構造化タスクでは `think` を無効にする。実測で有無による精度差は無かった（正答 3/3）
- 到達不可・タイムアウト・スキーマ違反のいずれも例外を投げず None を返す。
  呼び出し側は Claude API にフォールバックする（機能は落とさずコストを払って動かす）

このモジュールは Django モデルに触らない。AILog への記録は llm_advisor 側で行う。
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

# ローカルは「速いから使う」のではなく「遅くても困らないから使う」層に当てる。
# 8B で 58 tok/s、コールドロード 3.3秒。既定値はバッチ用途を想定した長めの値。
DEFAULT_TIMEOUT = 300


def _base_url() -> str:
    return getattr(
        settings, "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
    ).rstrip("/")


def _model() -> str:
    return getattr(settings, "OLLAMA_CHAT_MODEL", "qwen3:8b")


def _timeout() -> int:
    return int(getattr(settings, "OLLAMA_CHAT_TIMEOUT", DEFAULT_TIMEOUT))


def _num_ctx() -> int:
    """コンテキスト長。

    実測では 14B で ctx を伸ばすと KV キャッシュが VRAM から溢れて
    CPU に落ち、生成速度が半減〜1/4になる。8B でも無制限には伸ばせない。
    既定 8192 は「8B + 中程度のコンテキスト」で GPU に収まる値。
    """
    return int(getattr(settings, "OLLAMA_CHAT_NUM_CTX", 8192))


def _keep_alive() -> str:
    """モデルを VRAM に常駐させる時間。

    ホスト側に OLLAMA_KEEP_ALIVE=0 が設定されているため、指定しないと
    1リクエストごとにアンロードされ、次回に再ロードが丸ごと乗る。
    リクエストの keep_alive はサーバ側の環境変数を上書きする。
    単発呼び出しなら "0"、バッチ中は "10m" を呼び出し側から渡す。
    """
    return str(getattr(settings, "OLLAMA_KEEP_ALIVE", "5m"))


def is_configured() -> bool:
    """ローカル生成が有効化されているか。"""
    return bool(getattr(settings, "OLLAMA_CHAT_ENABLED", False)) and bool(_base_url())


def chat_json(
    prompt: str,
    schema: dict,
    *,
    system_prompt: str = "",
    keep_alive: str | None = None,
    num_ctx: int | None = None,
    timeout: int | None = None,
) -> dict | None:
    """ローカルモデルに JSON Schema 付きで問い合わせる。

    Args:
        prompt: ユーザープロンプト（文字列のみ。画像は扱えない）
        schema: 出力を拘束する JSON Schema オブジェクト。必須。
        system_prompt: システムプロンプト
        keep_alive: 常駐時間。単発は "0"、バッチ中は "10m" を渡す
        num_ctx: コンテキスト長の上書き
        timeout: 秒。既定は OLLAMA_CHAT_TIMEOUT

    Returns:
        成功時 {"text", "parsed", "input_tokens", "output_tokens", "model_id"}。
        失敗時は None（例外は投げない）。
    """
    if not schema:
        raise ValueError("chat_json には JSON Schema が必須です。")
    if not is_configured():
        return None

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": _model(),
        "messages": messages,
        "stream": False,
        # 構造化タスクでは思考を切る。精度は変わらず出力トークンだけ減る。
        "think": False,
        "format": schema,
        "keep_alive": keep_alive if keep_alive is not None else _keep_alive(),
        "options": {
            # 抽出・選択タスクなので揺らがせない。
            "temperature": 0,
            "num_ctx": num_ctx if num_ctx is not None else _num_ctx(),
        },
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        f"{_base_url()}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            req, timeout=timeout if timeout is not None else _timeout()
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        # 到達不可でも例外は投げない。呼び出し側は Claude API へ落ちる。
        logger.warning("ローカル推論に失敗しました（APIへフォールバック）: %s", e)
        return None

    text = (data.get("message") or {}).get("content", "")
    if not text:
        logger.warning("ローカル推論の応答が空でした（APIへフォールバック）")
        return None

    # format に Schema を渡しているので素の JSON が返る。
    # それでも壊れていたらフォールバックさせる（握り潰して0件にしない）。
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "ローカル推論の出力が JSON として読めません（APIへフォールバック）: %s", e
        )
        return None

    return {
        "text": text,
        "parsed": parsed,
        "input_tokens": data.get("prompt_eval_count", 0) or 0,
        "output_tokens": data.get("eval_count", 0) or 0,
        "model_id": data.get("model") or _model(),
    }
