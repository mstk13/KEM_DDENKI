from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TenantModel


class EvalItem(TenantModel):
    """評価項目マスタ。"""

    section = models.TextField("セクション", help_text="共通 or 職種名")
    num = models.IntegerField("項目番号")
    name = models.TextField("項目名")
    description = models.TextField("説明", blank=True)
    max_score = models.IntegerField("最大スコア", default=5)
    choice_group = models.TextField("選択肢グループ", null=True, blank=True)
    sort_order = models.IntegerField("並び順", default=0)
    anchor_5 = models.TextField("5点基準", blank=True)
    anchor_3 = models.TextField("3点基準", blank=True)
    anchor_1 = models.TextField("1点基準", blank=True)
    free_text = models.TextField("自由記述", null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "評価項目"
        verbose_name_plural = "評価項目"
        ordering = ["section", "sort_order", "num"]

    def __str__(self):
        return f"[{self.section}] {self.num}. {self.name}"


class SurveyQuestion(TenantModel):
    """評価項目ごとの質問。"""

    item = models.ForeignKey(
        EvalItem,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="評価項目",
    )
    qnum = models.TextField("質問番号")
    text = models.TextField("質問文")
    sort_order = models.IntegerField("並び順", default=0)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "質問"
        verbose_name_plural = "質問"
        ordering = ["sort_order", "qnum"]

    def __str__(self):
        return f"{self.qnum}: {self.text[:30]}"


class Evaluation(TenantModel):
    """評価メインレコード。"""

    employee = models.ForeignKey(
        "workers.Worker",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations_as_employee",
        verbose_name="被評価者",
    )
    employee_name = models.TextField("被評価者名")
    role = models.TextField("職種", blank=True)
    period = models.TextField("評価期間", blank=True)
    evaluator = models.ForeignKey(
        "workers.Worker",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations_as_evaluator",
        verbose_name="評価者",
    )
    evaluator_name = models.TextField("評価者名", null=True, blank=True)
    choice_field = models.JSONField("選択肢フィールド", default=dict, blank=True)
    max_total = models.IntegerField("最大合計点", default=0)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "評価"
        verbose_name_plural = "評価"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee_name} ({self.period})"

    @property
    def total_score(self):
        return self.scores.aggregate(total=models.Sum("score"))["total"] or 0

    @property
    def score_percent(self):
        if self.max_total == 0:
            return 0
        return round(self.total_score / self.max_total * 100, 1)


class EvalScore(TenantModel):
    """項目ごとのスコア。"""

    evaluation = models.ForeignKey(
        Evaluation,
        on_delete=models.CASCADE,
        related_name="scores",
        verbose_name="評価",
    )
    item_num = models.IntegerField("項目番号")
    item_name = models.TextField("項目名")
    score = models.IntegerField("スコア", default=0)
    comment = models.TextField("コメント", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "評価スコア"
        verbose_name_plural = "評価スコア"
        ordering = ["item_num"]

    def __str__(self):
        return f"{self.item_name}: {self.score}"


class EvalAnswer(TenantModel):
    """個別質問への回答。"""

    evaluation = models.ForeignKey(
        Evaluation,
        on_delete=models.CASCADE,
        related_name="answers",
        verbose_name="評価",
    )
    item = models.ForeignKey(
        EvalItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="answers",
        verbose_name="評価項目",
    )
    item_name = models.TextField("項目名")
    qnum = models.TextField("質問番号")
    question_text = models.TextField("質問文")
    answer = models.IntegerField("回答 (1-5)", null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "回答"
        verbose_name_plural = "回答"
        ordering = ["qnum"]

    def __str__(self):
        return f"{self.qnum}: {self.answer}"


class EvalOverall(TenantModel):
    """総合フリーテキスト回答。"""

    evaluation = models.ForeignKey(
        Evaluation,
        on_delete=models.CASCADE,
        related_name="overalls",
        verbose_name="評価",
    )
    qnum = models.TextField("質問番号")
    question_text = models.TextField("質問文")
    answer_text = models.TextField("回答テキスト", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "総合回答"
        verbose_name_plural = "総合回答"

    def __str__(self):
        return f"{self.qnum}: {self.answer_text[:30]}"


class EvaluatorTarget(TenantModel):
    """評価者 -> 被評価者 の割当。"""

    evaluator_name = models.TextField("評価者名")
    target_name = models.TextField("被評価者名")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "評価者割当"
        verbose_name_plural = "評価者割当"
        unique_together = [("company", "evaluator_name", "target_name")]
        ordering = ["evaluator_name", "target_name"]

    def __str__(self):
        return f"{self.evaluator_name} -> {self.target_name}"
