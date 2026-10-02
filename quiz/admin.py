from django.contrib import admin
from .models import (
    Category, Material, MaterialLink, Question, QuestionChoice,
    Score, QuestionResponse, Badge, UserBadge,
    ActivityComment, ActivityReaction,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'key', 'icon', 'has_links', 'link_mode', 'order', 'is_active')
    list_filter = ('is_active', 'has_links', 'link_mode')
    search_fields = ('key', 'name', 'label')
    ordering = ('order',)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    # 🆕 TEMPORARY: uses `category_new` while we migrate; will rename back to `category` later
    list_display = ('__str__', 'category', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    search_fields = ('source_name', 'title', 'slug')
    prepopulated_fields = {'slug': ('source_name', 'chapter_number', 'title')}


@admin.register(MaterialLink)
class MaterialLinkAdmin(admin.ModelAdmin):
    list_display = ('material', 'link_type', 'url', 'order')
    list_filter = ('link_type',)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('material', 'order', 'short_text')
    list_filter = ('material__category',)   # 🆕 FIXED (double-underscore traversal)
    search_fields = ('text',)

    def short_text(self, obj):
        return obj.text[:60]
    short_text.short_description = 'نص السؤال'


@admin.register(QuestionChoice)
class QuestionChoiceAdmin(admin.ModelAdmin):
    list_display = ('question', 'key', 'text', 'is_correct', 'order')
    list_filter = ('is_correct', 'key')


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'material', 'score_value', 'time_taken_seconds', 'created_at')
    list_filter = ('material__category',)   # 🆕 FIXED
    search_fields = ('user__username',)


@admin.register(QuestionResponse)
class QuestionResponseAdmin(admin.ModelAdmin):
    list_display = ('score', 'question', 'selected_choice', 'is_correct')
    list_filter = ('is_correct',)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'condition_type', 'threshold_value',
                    'category_filter', 'is_active')       # 🆕 FIXED
    list_filter = ('condition_type', 'is_active', 'category_filter')   # 🆕 FIXED


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge', 'earned_at')
    list_filter = ('badge',)


@admin.register(ActivityComment)
class ActivityCommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'text', 'created_at')
    list_filter = ('created_at',)


@admin.register(ActivityReaction)
class ActivityReactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'emoji', 'label', 'created_at')
    list_filter = ('emoji',)