from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.evaluation.models import (
    EvalAnswer,
    EvalItem,
    EvalOverall,
    EvalScore,
    Evaluation,
    EvaluatorTarget,
    SurveyQuestion,
)


class SurveyQuestionInline(admin.TabularInline):
    model = SurveyQuestion
    extra = 0


class EvalScoreInline(admin.TabularInline):
    model = EvalScore
    extra = 0


class EvalAnswerInline(admin.TabularInline):
    model = EvalAnswer
    extra = 0


class EvalOverallInline(admin.TabularInline):
    model = EvalOverall
    extra = 0


@admin.register(EvalItem)
class EvalItemAdmin(SimpleHistoryAdmin):
    list_display = ("section", "num", "name", "max_score", "sort_order", "company")
    list_filter = ("section", "company")
    search_fields = ("name",)
    inlines = [SurveyQuestionInline]


@admin.register(SurveyQuestion)
class SurveyQuestionAdmin(SimpleHistoryAdmin):
    list_display = ("qnum", "text", "item", "company")
    list_filter = ("company",)


@admin.register(Evaluation)
class EvaluationAdmin(SimpleHistoryAdmin):
    list_display = ("employee_name", "role", "period", "evaluator_name", "max_total", "company")
    list_filter = ("role", "period", "company")
    search_fields = ("employee_name", "evaluator_name")
    inlines = [EvalScoreInline, EvalAnswerInline, EvalOverallInline]


@admin.register(EvalScore)
class EvalScoreAdmin(SimpleHistoryAdmin):
    list_display = ("evaluation", "item_num", "item_name", "score", "company")
    list_filter = ("company",)


@admin.register(EvalAnswer)
class EvalAnswerAdmin(SimpleHistoryAdmin):
    list_display = ("evaluation", "qnum", "question_text", "answer", "company")
    list_filter = ("company",)


@admin.register(EvalOverall)
class EvalOverallAdmin(SimpleHistoryAdmin):
    list_display = ("evaluation", "qnum", "question_text", "company")
    list_filter = ("company",)


@admin.register(EvaluatorTarget)
class EvaluatorTargetAdmin(SimpleHistoryAdmin):
    list_display = ("evaluator_name", "target_name", "company")
    list_filter = ("company",)
    search_fields = ("evaluator_name", "target_name")
