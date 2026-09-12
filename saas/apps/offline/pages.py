"""圏外でも開けて、圏外で保存できる入力画面（ADR-0048）。

Service Worker は、ここに載っている URL の画面を電波のあるときに開いたら端末に控え、
圏外ではその控えを出す。これらの画面からの送信が通信エラーになったら、入力を端末に保存する。

正規表現は JavaScript の RegExp にもそのまま渡すので、両方で同じ意味になる書き方
（^ $ \\d + と文字）だけを使う。画面を足したら、そのビューに offline_resendable を付ける
（tests/test_offline_outbox.py が両方そろっているかを確かめる）。
"""

OFFLINE_FORM_PATTERNS = (
    # 資格（資格証の画像）
    r"^/workers/\d+/qualifications/new/$",
    r"^/workers/qualifications/\d+/edit/$",
    # 健康診断（結果の書類）
    r"^/workers/\d+/health/new/$",
    r"^/workers/health/\d+/edit/$",
    # 納品の記録（納品書の画像）
    r"^/materials/po/\d+/delivery/new/$",
)
