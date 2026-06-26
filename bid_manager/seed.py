"""デモデータ投入スクリプト。

実サイトのスクレイピング設定をしなくても、UI と分析機能をすぐ試せるよう、
サンプルの案件・費用・競合・対象サイト・単価を投入する。

    python seed.py
"""
from __future__ import annotations

from datetime import date, timedelta

import database as db


def run() -> None:
    db.init_db()
    today = date.today()

    # 対象サイト（例）
    db.add_target("東京都電子調達システム", "https://www.e-procurement.metro.tokyo.lg.jp/", "東京都")
    db.add_target("神奈川県電子入札", "https://nyusatsu.e-kanagawa.lg.jp/", "神奈川県")

    samples = [
        # (title, client, region, category, deadline_offset, budget, status,
        #  estimate, actual, competitor, comp_amount)
        ("〇〇小学校 電気設備改修工事", "東京都教育委員会", "東京都", "電気設備",
         5, 12_000_000, "見積作成中", None, None, None, None),
        ("市庁舎 受変電設備更新工事", "横浜市", "神奈川県", "受変電設備",
         2, 45_000_000, "入札済", 42_000_000, None, None, None),
        ("県道トンネル 照明設備工事", "埼玉県県土整備部", "埼玉県", "照明設備",
         12, 8_500_000, "受注", 8_200_000, 6_900_000, None, None),
        ("公民館 幹線・動力設備工事", "千葉市", "千葉県", "受変電設備",
         -3, 6_300_000, "失注", 6_100_000, None, "△△電設株式会社", 5_800_000),
        ("体育館 LED照明更新", "茨城県", "茨城県", "照明設備",
         20, 3_200_000, "検討中", None, None, None, None),
        ("浄水場 配線・弱電工事", "群馬県企業局", "群馬県", "通信・弱電",
         8, 9_800_000, "新着", None, None, None, None),
    ]

    for (title, client, region, cat, off, budget, status,
         est, act, comp, comp_amt) in samples:
        pid = db.add_project(
            title=title, client=client, region=region, category=cat,
            deadline=(today + timedelta(days=off)).isoformat(),
            budget=budget, source_url="https://example.com/bid", status=status,
        )
        if pid is None:
            continue
        if est is not None or act is not None:
            db.upsert_cost(pid, estimate_amount=est, actual_cost=act,
                           memo="デモデータ")
        if comp:
            db.add_competitor(pid, competitor_name=comp, competitor_amount=comp_amt,
                              source="自治体サイト", memo="デモデータ")

    # 単価マスタ
    for cat, item, unit, price in [
        ("電気工事", "VVFケーブル 2.0mm", "m", 120),
        ("電気工事", "VVFケーブル 1.6mm", "m", 90),
        ("照明設備", "LEDベースライト 40W型", "台", 8_500),
        ("受変電設備", "高圧キュービクル 一式", "式", 1_800_000),
        ("通信・弱電", "LANケーブル Cat6", "m", 80),
    ]:
        db.add_unit_price(category=cat, item_name=item, unit=unit, unit_price=price,
                          memo="デモ単価")

    print("デモデータを投入しました。`streamlit run app.py` で起動してください。")


if __name__ == "__main__":
    run()
