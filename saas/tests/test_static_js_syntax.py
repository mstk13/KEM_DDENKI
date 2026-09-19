"""static/js の JavaScript が文法どおりに読めることを確かめる。

app.js の文字列に本物の改行が入り（「\\n」と書くべきところ）、ファイル全体が読み込めなくなった。
app.js はサイドバーの見出しを開く処理も持つため、本番で「ホーム以外を開けない」状態になった。
Python のテストでは JavaScript を動かさないので、node の文法チェックにかけて CI で止める。
node が無い環境（手元の Windows など）では飛ばす。CI（ubuntu-latest）には node が入っている。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent.parent / "static" / "js"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node が無い環境では文法チェックできない")
@pytest.mark.parametrize("path", sorted(JS_DIR.glob("*.js")), ids=lambda p: p.name)
def test_JavaScriptが文法どおりに読める(path):
    result = subprocess.run(
        [NODE, "--check", str(path)], capture_output=True, text=True, encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr


def test_確かめるファイルがある():
    # 置き場所が変わって何も確かめていない、ということにならないように
    assert (JS_DIR / "app.js").exists()
