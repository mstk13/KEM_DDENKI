"""ADR の番号とファイル名を機械で見張る（ADR-0086）。

番号の重複が4回起きている（0022 / 0070 / 0080 / 0082）。原因は、並行して
進んだ別々の作業がそれぞれ「次の空き番号」を同時に取ること。マージされるまで
相手の番号は見えないので、**人の注意では防げない**。実際にこのテストを書く
直前にも、0083 を取った直後に別の 0083 がマージされている。

## 過去の重複は振り直さない

どちらの ADR も既にコード・テスト・コミットメッセージから番号で参照されている。
片方を振り直すと:

- **コミットメッセージは書き換えられない。** 過去の「ADR-0082」が別の決定を
  指すようになる。曖昧なままより悪い（誤った先を指す）
- 散在する参照コメントを全て追う必要があり、漏れれば嘘が残る

そこで**過去は凍結し、これ以上増やさない**。既知の重複は KNOWN_DUPLICATES に
明記し、それ以外の重複でテストを落とす。番号だけで一意に決まらない4つは、
参照する側がファイル名で特定する。

## 新しい ADR を書くとき

このテストが落ちたら、メッセージに出る空き番号を使ってファイル名を変える。
マージ直前に他の作業とぶつかることがあるので、**番号は最後に確定させるのが安全**。
"""

import re
from collections import Counter
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "saas" / "adr"

# ADR-0001-lowercase-slug.md
ADR_FILENAME = re.compile(r"^ADR-(\d{4})-[a-z0-9-]+\.md$")

# 凍結した既知の重複。上の理由により振り直さない。
# **ここに足して重複を通してはいけない。** 新しい ADR は空き番号を使う。
KNOWN_DUPLICATES = {
    "0022",  # bid-schedule-gantt / position-based-app-access
    "0070",  # attendance-office-task / date-inputs-rendered-by-widget
    "0080",  # daily-report-missing-alerts / estimation-documents-and-inputs
    "0082",  # certificate-pdf-import / worker-app-access-matrix
}


def _adr_files():
    return sorted(p.name for p in ADR_DIR.glob("ADR-*.md"))


def _next_free_number(numbers) -> str:
    """次に使う番号（4桁）。落ちたときの案内に使う。

    「一番小さい空き番号」ではなく**最大+1**を返す。実際の付け方が連番であり、
    欠番（0001〜0004 は存在しない）を埋めると時系列が崩れて読みにくくなる。
    """
    return f"{max(int(n) for n in numbers) + 1:04d}"


def test_ADRのファイル名が規則どおりである():
    """ADR-0001-lowercase-slug.md の形。日本語・大文字・空白は使わない。"""
    bad = [name for name in _adr_files() if not ADR_FILENAME.match(name)]

    assert not bad, (
        "ADR のファイル名は ADR-0001-lowercase-slug.md の形にしてください"
        "（4桁の番号 + 半角英小文字・数字・ハイフンの説明 + .md）:\n  "
        + "\n  ".join(bad)
    )


def test_ADRの番号が重複していない():
    """凍結した4つ以外に重複を増やさない。"""
    names = _adr_files()
    numbers = [m.group(1) for name in names if (m := ADR_FILENAME.match(name))]
    duplicated = {n for n, count in Counter(numbers).items() if count > 1}

    new_duplicates = duplicated - KNOWN_DUPLICATES
    assert not new_duplicates, (
        "ADR の番号が重複しています: "
        + ", ".join(sorted(new_duplicates))
        + f"\n次に使う番号は {_next_free_number(numbers)} です。"
        "\nファイル名の番号を変えてください（KNOWN_DUPLICATES には足さないこと）。"
        "\n重複しているファイル:\n  "
        + "\n  ".join(
            name for name in names
            if (m := ADR_FILENAME.match(name)) and m.group(1) in new_duplicates
        )
    )


def test_凍結した重複の一覧が実態と合っている():
    """振り直して重複が解けたら、KNOWN_DUPLICATES からも消す。

    残しておくと「まだ重複している」という嘘の記録になり、次の人が
    振り直し済みの番号を避けてしまう。
    """
    names = _adr_files()
    numbers = [m.group(1) for name in names if (m := ADR_FILENAME.match(name))]
    duplicated = {n for n, count in Counter(numbers).items() if count > 1}

    stale = KNOWN_DUPLICATES - duplicated
    assert not stale, (
        "KNOWN_DUPLICATES に、もう重複していない番号が残っています: "
        + ", ".join(sorted(stale))
        + "\nテストの KNOWN_DUPLICATES から消してください。"
    )
