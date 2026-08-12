"""<script> へ埋め込む JSON のエスケープ。

現場名・プロジェクト名・氏名は利用者が入力する値で、そのまま
<script> の中に書き出すとタグを閉じてスクリプトを注入できる。
"""

import json

from apps.core.json_utils import json_for_script

CLOSE_TAG = "</script>"


class TestJsonForScript:
    def test_closing_tag_cannot_escape_the_script_block(self):
        out = json_for_script({"name": f"{CLOSE_TAG}<script>alert(1)</script>"})
        assert CLOSE_TAG not in out
        assert "<" not in out
        assert ">" not in out

    def test_value_survives_the_round_trip(self):
        # エスケープしても JSON としては同じ文字列に戻る
        original = {"name": f"A&B {CLOSE_TAG} <b>", "n": 1}
        assert json.loads(json_for_script(original)) == original

    def test_line_separators_are_escaped(self):
        # U+2028 / U+2029 は JSON では通るが JavaScript では改行になり構文を壊す
        original = {'name': 'a' + chr(0x2028) + 'b' + chr(0x2029) + 'c'}
        out = json_for_script(original)
        assert chr(0x2028) not in out
        assert chr(0x2029) not in out
        assert json.loads(out) == original

    def test_japanese_is_not_escaped(self):
        # 読みやすさのため日本語はそのまま出す
        assert "現場" in json_for_script({"name": "現場"})

    def test_spaces_are_left_alone(self):
        assert json.loads(json_for_script({"name": "a b  c"}))["name"] == "a b  c"
