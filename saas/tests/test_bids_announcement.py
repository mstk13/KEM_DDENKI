"""公告PDFからの工事概要・参加要件の抽出。

本文は 2026-08-14 に実際の公告PDFから取り出したものを短くして使う。
- 防衛省北関東防衛局 R8k-068（入札公告 形式）
- 国土交通省関東地方整備局 東京第二営繕事務所（手続き開始の公示 形式）
ネットワークには触らない。
"""
import pytest

from apps.bids.announcement import (
    extract_grade_floor,
    extract_grades,
    extract_score_floor,
    extract_sections,
    is_garbled,
    split_sections,
)
from apps.bids.models import BidProject
from apps.bids.services import announcement_candidates, fill_announcement

# 「入札公告」形式。見出しは「番号 + 空白 + 見出し語」。
KOUKOKU = """\
入 札 公 告（建設工事）
次のとおり一般競争入札に付す。
１ 工事概要
(1) 工事名 入間（８）厚生棟改修電気工事
(2) 工事場所 埼玉県狭山市
(3) 工事内容 本工事は、以下に掲げる電気工事を行うものである。
工事内容：空調設備改修に係る電気工事 一式
(4) 工期 契約締結日の翌日から令和10年６月30日まで
1
２ 競争参加資格
(1) 予算決算及び会計令第70条及び第71条の規定に該当しない者であること。
(2) 防衛省における令和７・８年度一般競争参加資格のうち、「電気工事」で
級別の格付を受け、北関東防衛局に競争参加を希望していること。
2
３ 総合評価に関する事項
(1) 落札者の決定は総合評価落札方式による。
４ 入札手続等
(1) 担当部局 北関東防衛局 総務部契約課
５ その他
"""

# 「手続き開始の公示」形式。見出しは「番号 + 全角ピリオド」で、
# 参加資格の節の名前が違う。表の行が見出しに紛れやすい。
KOUJI = """\
公募型指名競争入札に係る手続き開始の公示（建設工事）
１．工事概要
（１）工事名 千葉労災特別介護施設（２６）電気設備改修その他工事
（２）工事場所 千葉県四街道市
２．技術資料等の提出を求める対象者に必要な要件
（１）関東地方整備局の令和７・８年度一般競争（指名競争）
参加資格業者のうち電気設備工事Ｂ等級又はＣ等級に認定されている者であること
３. 総合評価に関する事項
（１）評価項目
４．入札手続等
（１）担当部局 東京第二営繕事務所
４．入札手続等 入札説明書の交付期間及び受 令和８年７月１７日（金）から
４．入札手続等 入札の締切 令和８年９月２５日（金）
５．その他
"""


class TestSectionSplit:
    def test_koukoku_form(self):
        result = extract_sections(KOUKOKU)
        assert "入間（８）厚生棟改修電気工事" in result["work_outline"]
        assert "空調設備改修に係る電気工事" in result["work_outline"]
        assert "予算決算及び会計令" in result["requirements"]
        # 次の章まで入り込まない
        assert "総合評価落札方式による" not in result["requirements"]

    def test_koji_form_with_different_heading(self):
        # 参加資格の節が「技術資料等の提出を求める対象者に必要な要件」
        result = extract_sections(KOUJI)
        assert "千葉労災特別介護施設" in result["work_outline"]
        assert "電気設備工事Ｂ等級又はＣ等級" in result["requirements"]

    def test_table_rows_are_not_headings(self):
        # 「４．入札手続等 入札説明書の交付期間及び受 令和８年…」は表の行。
        # 見出しと誤認すると章の切れ目がずれる。
        headings = [h for h, _ in split_sections(KOUJI)]
        assert "入札手続等" in headings
        assert not any("交付期間" in h for h in headings)
        assert not any("令和" in h for h in headings)

    def test_page_numbers_do_not_end_a_section(self):
        # 本文の途中に入るページ番号だけの行で章が切れないこと
        result = extract_sections(KOUKOKU)
        assert "級別の格付を受け" in result["requirements"]

    def test_no_headings(self):
        result = extract_sections("見出しのない文書です。")
        assert result["work_outline"] == ""
        assert result["requirements"] == ""
        assert result["garbled"] is False

    def test_empty(self):
        result = extract_sections("")
        assert result["work_outline"] == ""
        assert result["garbled"] is False


class TestGarbled:
    def test_cid_only_pdf_is_detected(self):
        # フォントに ToUnicode が無いPDFは (cid:NNN) しか取れない。
        # 章立てが取れないのを「公告に書いていない」と誤解しないため。
        text = "".join(f"(cid:{i})" for i in range(200))
        assert is_garbled(text)
        assert extract_sections(text)["garbled"] is True

    def test_normal_text_is_not_garbled(self):
        assert not is_garbled(KOUKOKU)


class TestGradeEnumeration:
    """公告は等級を「下限」ではなく「列挙」で指定することが多い。

    本文は 2026-08-14 に国土交通省の実公告から取ったもの。
    """

    def test_enumeration(self):
        text = (
            "（１）関東地方整備局の令和７・８年度一般競争（指名競争）\n"
            "参加資格業者のうち電気設備工事Ｂ等級又はＣ等級に認定されている者であること"
        )
        assert extract_grades(text) == "BC"

    def test_single_grade(self):
        text = "参加資格業者のうち電気設備工事Ｂ等級に認定されている者であること"
        assert extract_grades(text) == "B"

    def test_grade_of_form(self):
        # 中部地方整備局は「電気設備工事に係るＡ等級の…一般競争参加資格」と書く
        text = (
            "(2) 中部地方整備局における電気設備工事に係るＡ等級の"
            "令和７・８年度一般競争参加資格の認定を受けていること"
        )
        assert extract_grades(text) == "A"

    def test_performance_score_grade_is_ignored(self):
        # 工事成績評定点の話に出てくる等級らしき文字を拾わない
        assert extract_grades("工事成績評定点が65点未満のものを除く") == ""

    def test_nothing(self):
        assert extract_grades("") == ""


class TestScoreFloor:
    """防衛省は等級ではなく点数で切る。"""

    def test_sougou_shinsa_suuchi(self):
        text = (
            "(4) 防衛省競争参加資格の「電気工事」に係る総合審査数値"
            "（資格審査結果通知書の記３の総合審査数値欄の点数）が780点以上であること。"
        )
        assert extract_score_floor(text) == 780

    def test_keiei_jikou_hyouka_suuchi(self):
        text = (
            "(4) 代表者は、防衛省競争参加資格の「電気工事」に係る経営事項評価数値"
            "（資格審査結果通知書の記３の経営事項評価数値欄の点数）が1,100点以上で"
            "あること。ただし、代表者以外の構成員は、経営事項評価数値が1,000点以上"
            "であること。"
        )
        # 共同企業体の構成員向けの緩い点数ではなく、単体で必要な厳しいほうを採る
        assert extract_score_floor(text) == 1100

    def test_performance_score_is_ignored(self):
        # 「工事成績評定点」「65点以上の工事とみなす」は資格の点数ではない
        text = (
            "ただし、工事成績評定点が65点未満のものを除くものとし、"
            "工事成績のない工事については、検査に合格している証明をもって"
            "65点以上の工事とみなす。"
        )
        assert extract_score_floor(text) is None

    def test_nothing(self):
        assert extract_score_floor("") is None
        assert extract_score_floor("「電気工事」で級別の格付を受けていること") is None


class TestGradeFloor:
    def test_floor_is_extracted(self):
        assert extract_grade_floor("「電気設備工事」のＤ等級以上であること") == "D"
        assert extract_grade_floor("B等級以上の認定を受けている者") == "B"

    def test_enumeration_is_not_a_floor(self):
        # 「Ｂ等級又はＣ等級」は下限ではなく列挙。大小比較に使うと誤判定になる
        assert extract_grade_floor("電気設備工事Ｂ等級又はＣ等級に認定されている者") == ""

    def test_loosest_floor_wins(self):
        assert extract_grade_floor("Ａ等級以上、またはＣ等級以上") == "C"

    def test_nothing(self):
        assert extract_grade_floor("") == ""
        assert extract_grade_floor("「電気工事」で級別の格付を受けていること") == ""


@pytest.mark.django_db
class TestFillAnnouncement:
    def _project(self, company_a, user_a, **kwargs):
        defaults = {
            "title": "入間（８）厚生棟改修電気工事",
            "source_url": "https://example.go.jp/kokoku.pdf",
        }
        defaults.update(kwargs)
        return BidProject.unscoped.create(
            company=company_a, created_by=user_a, **defaults,
        )

    def _stub(self, monkeypatch, **result):
        from apps.bids import announcement

        payload = {
            "work_outline": "工事内容：空調設備改修に係る電気工事 一式",
            "requirements": "「電気工事」のＤ等級以上であること",
            "required_grade": "D",
            "required_grades": "",
            "required_score": None,
            "headings": [],
            "garbled": False,
        }
        payload.update(result)
        monkeypatch.setattr(announcement, "extract_from_url", lambda url: payload)

    def test_fills_empty_fields(self, monkeypatch, company_a, user_a):
        self._stub(monkeypatch)
        project = self._project(company_a, user_a)
        assert fill_announcement(project) is True

        project.refresh_from_db()
        assert "空調設備改修" in project.work_outline
        assert "Ｄ等級以上" in project.requirements
        assert project.required_grade == "D"

    def test_does_not_overwrite_edited_text(self, monkeypatch, company_a, user_a):
        self._stub(monkeypatch)
        project = self._project(
            company_a, user_a,
            work_outline="現地調査済み。既設盤は3面。",
            required_grade="B",
        )
        fill_announcement(project)

        project.refresh_from_db()
        assert project.work_outline == "現地調査済み。既設盤は3面。"
        assert project.required_grade == "B"
        # 空いていた項目は埋まる
        assert "Ｄ等級以上" in project.requirements

    def test_skips_project_without_source_url(self, monkeypatch, company_a, user_a):
        self._stub(monkeypatch)
        project = self._project(company_a, user_a, source_url="")
        assert fill_announcement(project) is False

    def test_falls_back_to_next_document(self, monkeypatch, company_a, user_a):
        """先頭の公開文書が読めなくても、次の文書で取り込む。

        1案件に複数の文書がぶら下がり、先頭が公告とは限らない。
        「立川防災合同庁舎（２６）電気設備改修工事」は先頭が
        「技術資料収集に係る掲示」で、しかも文字が読めないPDFだった。
        """
        from apps.bids import announcement

        garbled = {
            "work_outline": "", "requirements": "", "required_grade": "",
            "required_grades": "", "required_score": None,
            "headings": [], "garbled": True,
        }
        good = {
            "work_outline": "工事内容：電気設備改修 一式",
            "requirements": "電気設備工事Ｂ等級に認定されている者であること",
            "required_grade": "", "required_grades": "B", "required_score": None,
            "headings": [], "garbled": False,
        }
        monkeypatch.setattr(
            announcement, "extract_from_url",
            lambda url: good if url.endswith("2") else garbled,
        )
        project = self._project(
            company_a, user_a,
            source_url="https://example.go.jp/doc1",
            document_urls="https://example.go.jp/doc1\nhttps://example.go.jp/doc2",
        )
        assert fill_announcement(project) is True

        project.refresh_from_db()
        assert "電気設備改修" in project.work_outline
        assert project.required_grades == "B"
        # 実際に読めた文書を情報源として残す
        assert project.source_url == "https://example.go.jp/doc2"

    def test_all_documents_unreadable(self, monkeypatch, company_a, user_a):
        self._stub(
            monkeypatch,
            work_outline="", requirements="", required_grade="",
            required_grades="", required_score=None, garbled=True,
        )
        project = self._project(
            company_a, user_a,
            document_urls="https://example.go.jp/a\nhttps://example.go.jp/b",
        )
        assert fill_announcement(project) is False
        project.refresh_from_db()
        assert project.work_outline == ""

    def test_candidates_order(self, company_a, user_a):
        project = self._project(
            company_a, user_a,
            source_url="https://example.go.jp/first",
            document_urls="https://example.go.jp/first\nhttps://example.go.jp/second",
        )
        assert announcement_candidates(project) == [
            "https://example.go.jp/first",
            "https://example.go.jp/second",
        ]

    def test_garbled_pdf_leaves_fields_empty(self, monkeypatch, company_a, user_a):
        self._stub(
            monkeypatch,
            work_outline="", requirements="", required_grade="", garbled=True,
        )
        project = self._project(company_a, user_a)
        assert fill_announcement(project) is False

        project.refresh_from_db()
        assert project.work_outline == ""
        assert project.requirements == ""
