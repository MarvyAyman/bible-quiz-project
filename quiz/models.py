from django.db import models
from django.contrib.auth.models import User

class Quiz(models.Model):
    book_name = models.CharField(max_length=100, verbose_name="اسم السفر")
    chapter_number = models.IntegerField(verbose_name="رقم الأصحاح")
    title = models.CharField(max_length=200, blank=True, null=True, verbose_name="عنوان الأصحاح (اختياري)")
    slug = models.SlugField(max_length=250, unique=True, blank=True, allow_unicode=True, verbose_name="رابط الـ Slug")
    is_active = models.BooleanField(default=False, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")

    class Meta:
        verbose_name = "مسابقة"
        verbose_name_plural = "المسابقات"

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base_slug = f"{self.book_name}-{self.chapter_number}"
            if self.title:
                base_slug += f"-{self.title}"
            # Remove consecutive dashes that come from spaces in Arabic text
            import re
            self.slug = re.sub(r'-{2,}', '-', base_slug.replace(" ", "-")).strip('-')
        super().save(*args, **kwargs)

    @property
    def question_count(self):
        return self.questions.count()

    def __str__(self):
        return f"{self.book_name} - أصحاح {self.chapter_number} {f'({self.title})' if self.title else ''}"


class Question(models.Model):
    CHOICE_KEYS = [('a', 'أ'), ('b', 'ب'), ('c', 'ج'), ('d', 'د')]

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")
    text = models.TextField(verbose_name="نص السؤال")
    choice_a = models.CharField(max_length=500, verbose_name="الاختيار أ")
    choice_b = models.CharField(max_length=500, verbose_name="الاختيار ب")
    choice_c = models.CharField(max_length=500, blank=True, verbose_name="الاختيار ج")
    choice_d = models.CharField(max_length=500, blank=True, verbose_name="الاختيار د")
    correct_choice = models.CharField(max_length=1, choices=CHOICE_KEYS, default='a', verbose_name="الإجابة الصحيحة")
    explanation = models.TextField(blank=True, verbose_name="التفسير")

    class Meta:
        ordering = ['order']
        verbose_name = "سؤال"
        verbose_name_plural = "الأسئلة"

    def __str__(self):
        return f"{self.quiz} - س{self.order}: {self.text[:40]}"


class Score(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scores")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="scores")
    score_value = models.IntegerField(verbose_name="الدرجة")
    time_taken_seconds = models.IntegerField(verbose_name="الوقت المستغرق بالثواني")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ المحاولة")

    class Meta:
        verbose_name = "نتيجة"
        verbose_name_plural = "النتائج"
        ordering = ['-score_value', 'time_taken_seconds']

    def __str__(self):
        return f"{self.user.username} - {self.quiz} ({self.score_value})"


class QuestionResponse(models.Model):
    score = models.ForeignKey(Score, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="responses")
    selected_choice = models.CharField(max_length=1, verbose_name="الاختيار المحدد")
    is_correct = models.BooleanField(verbose_name="هل الإجابة صحيحة؟")

    class Meta:
        verbose_name = "إجابة سؤال"
        verbose_name_plural = "إجابات الأسئلة"

    def __str__(self):
        return f"إجابة {self.score.user.username} على {self.question}"
