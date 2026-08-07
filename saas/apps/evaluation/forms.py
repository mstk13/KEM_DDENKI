from django import forms

from apps.evaluation.models import (
    EvalItem,
    EvalScore,
    Evaluation,
    EvaluatorTarget,
    SurveyQuestion,
)


class EvalItemForm(forms.ModelForm):
    class Meta:
        model = EvalItem
        fields = [
            "section", "num", "name", "description", "max_score",
            "choice_group", "sort_order", "anchor_5", "anchor_3", "anchor_1",
            "free_text",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "anchor_5": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "anchor_3": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "anchor_1": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "free_text": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class SurveyQuestionForm(forms.ModelForm):
    class Meta:
        model = SurveyQuestion
        fields = ["qnum", "text", "sort_order"]
        widgets = {
            "text": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class EvaluationCreateForm(forms.ModelForm):
    class Meta:
        model = Evaluation
        fields = [
            "employee", "employee_name", "role", "period",
            "evaluator", "evaluator_name",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class EvalScoreForm(forms.ModelForm):
    class Meta:
        model = EvalScore
        fields = ["score", "comment"]
        widgets = {
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class EvaluatorTargetForm(forms.ModelForm):
    class Meta:
        model = EvaluatorTarget
        fields = ["evaluator_name", "target_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
