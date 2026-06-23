from django.contrib import admin
from .models import Material, MaterialLink, Question, QuestionChoice, Score, QuestionResponse


class MaterialLinkInline(admin.TabularInline):
    model = MaterialLink
    extra = 0


class QuestionChoiceInline(admin.TabularInline):
    model = QuestionChoice
    extra = 0
    ordering = ['order']


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    ordering = ['order']


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('source_name', 'category', 'chapter_number', 'title', 'is_active', 'question_count', 'slug')
    list_filter = ('is_active', 'category', 'source_name')
    search_fields = ('source_name', 'title', 'slug')
    inlines = [MaterialLinkInline, QuestionInline]


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'material', 'score_value', 'time_taken_seconds', 'created_at')
    list_filter = ('material',)
    search_fields = ('user__username', 'user__email')


@admin.register(QuestionResponse)
class QuestionResponseAdmin(admin.ModelAdmin):
    list_display = ('score', 'question', 'selected_choice', 'is_correct')
    list_filter = ('is_correct', 'question__material')


admin.site.register(MaterialLink)
admin.site.register(Question)
admin.site.register(QuestionChoice)