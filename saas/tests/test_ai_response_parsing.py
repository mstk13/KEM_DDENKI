"""Claude のレスポンスからテキストを取り出す部分。

content[0] がテキストとは限らない。Claude Sonnet 5 は thinking を指定しないと
adaptive thinking が既定で有効になり、先頭が ThinkingBlock になる。
thinking が入るかはモデルが都度決めるので、決め打ちすると断続的に落ちる。
"""
import pytest

from apps.ai.services.llm_advisor import _first_text


class FakeBlock:
    def __init__(self, type_, text=None):
        self.type = type_
        if text is not None:
            self.text = text


class FakeMessage:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class TestFirstText:
    def test_plain_text_response(self):
        message = FakeMessage([FakeBlock("text", '{"ok": true}')])
        assert _first_text(message) == '{"ok": true}'

    def test_thinking_block_first(self):
        """2026-08-14 に本番で出た形。thinking が先頭に来る。"""
        message = FakeMessage([
            FakeBlock("thinking"),          # .text を持たない
            FakeBlock("text", '{"ok": true}'),
        ])
        assert _first_text(message) == '{"ok": true}'

    def test_thinking_only_reports_max_tokens(self):
        # thinking で max_tokens を使い切ると本文が返らない
        message = FakeMessage([FakeBlock("thinking")], stop_reason="max_tokens")
        with pytest.raises(ValueError, match="max_tokens"):
            _first_text(message)

    def test_no_text_block_names_what_came_back(self):
        message = FakeMessage([FakeBlock("thinking")], stop_reason="end_turn")
        with pytest.raises(ValueError, match="thinking"):
            _first_text(message)

    def test_empty_content(self):
        message = FakeMessage([], stop_reason="refusal")
        with pytest.raises(ValueError, match="refusal"):
            _first_text(message)
