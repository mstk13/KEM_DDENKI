"""テンプレートの <script> へ JSON を埋め込むための共通処理。"""

import json

# <script> の中に JSON を直接書き出すとき、値に "</script>" が含まれると
# そこでタグが閉じてしまい、続きが HTML として解釈される。
# 現場名・プロジェクト名・氏名などは利用者が入力する値なので、
# 素通しにするとスクリプトを注入できてしまう。
# JSON としては \uXXXX 表記でも同じ文字列なので、読み手側の変更は要らない。
_SCRIPT_UNSAFE = {
    ord("<"): "\\u003c",
    ord(">"): "\\u003e",
    ord("&"): "\\u0026",
    # U+2028 / U+2029（行区切り・段落区切り）。JSON では素の文字として許されるが
    # JavaScript の文字列リテラル中では改行として扱われ、構文を壊す。
    0x2028: "\\u2028",
    0x2029: "\\u2029",
}


def json_for_script(data, **dumps_kwargs) -> str:
    """<script> の中へそのまま書き出せる JSON 文字列を返す。

    テンプレート側では {{ value|safe }} で埋め込む。
    """
    dumps_kwargs.setdefault("ensure_ascii", False)
    return json.dumps(data, **dumps_kwargs).translate(_SCRIPT_UNSAFE)
