"""デモデータ投入（Claude API なしでUI・分析を試すため）。"""
from datetime import date, timedelta

import database


SAMPLES = [
    dict(industry="電材・資材", company_name="株式会社サンプル電材", rep_name="山田 太郎",
         business_overview="電気工事用の配線材・照明器具・分電盤などを扱う電材卸売業者。",
         sales_content="LED照明器具の新製品案内。既存蛍光灯からの置き換え提案。",
         phone="03-1234-5678", email="yamada@sample-denzai.co.jp", status="確認済"),
    dict(industry="電材・資材", company_name="関東電設資材", rep_name="井上 拓",
         business_overview="関東一円に電設資材を供給する専門商社。即日配送が強み。",
         sales_content="配線材・分電盤の在庫特価案内。定期納入の相談。",
         phone="03-3333-2222", email="inoue@kanto-shizai.jp", status="対応中"),
    dict(industry="通信・IT", company_name="東西通信システム", rep_name="鈴木 花子",
         business_overview="業務用無線・IP無線・ネットワーク機器の販売と保守を行う通信会社。",
         sales_content="現場向けの業務用無線・IP無線の導入提案。月額プランの見積り持参。",
         phone="045-987-6543", email="suzuki@tozai-tsushin.jp", status="対応中"),
    dict(industry="省エネ・環境", company_name="グリーンエナジー商事", rep_name="佐藤 健",
         business_overview="太陽光発電・蓄電池など再生可能エネルギー設備の販売・施工会社。",
         sales_content="太陽光パネル・蓄電池の販売代理店募集。施工事例集を持参。",
         phone="048-222-1111", email="sato@green-energy.co.jp", status="下書き"),
    dict(industry="オフィス・事務用品", company_name="日本オフィスサプライ", rep_name="高橋 実",
         business_overview="事務用品・工具・消耗品の通販と定期購買サービスを提供。",
         sales_content="事務用品・工具の定期購買サービス。カタログ配布のみ。",
         phone="03-5555-0000", email="", status="見送り"),
    dict(industry="金融・保険・リース", company_name="みらいリース", rep_name="中村 由美",
         business_overview="建設機材・車両のリースと事業者向け損害保険を扱うリース会社。",
         sales_content="工事車両・機材のリース＆保険パッケージの提案。",
         phone="03-7777-8888", email="nakamura@mirai-lease.jp", status="確認済"),
]


def run():
    database.init_db()
    today = date.today()
    for i, s in enumerate(SAMPLES):
        s = dict(s)
        s["visit_date"] = (today - timedelta(days=i * 3)).isoformat()
        s["received_date"] = s["visit_date"]
        database.add_visit(**s)
    print(f"{len(SAMPLES)} 件のデモデータを投入しました。")


if __name__ == "__main__":
    run()
