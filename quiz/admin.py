from django.contrib import admin
from .models import Quiz, Question, Score, QuestionResponse


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    ordering = ['order']


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('book_name', 'chapter_number', 'title', 'is_active', 'question_count', 'slug')
    list_filter = ('is_active', 'book_name')
    search_fields = ('book_name', 'title', 'slug')
    inlines = [QuestionInline]


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'quiz', 'score_value', 'time_taken_seconds', 'created_at')
    list_filter = ('quiz',)
    search_fields = ('user__username', 'user__email')


@admin.register(QuestionResponse)
class QuestionResponseAdmin(admin.ModelAdmin):
    list_display = ('score', 'question', 'selected_choice', 'is_correct')
    list_filter = ('is_correct', 'question__quiz')