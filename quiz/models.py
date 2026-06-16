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
            base_slug = f"{self.book_name} الاصحاح {self.chapter_number}"
            if self.title:
                base_slug += f" {self.title}"
            self.slug = base_slug.replace(" ", "-")
        super().save(*args, **kwargs)

    @property
    def question_count(self):
        return self.questions.count()

    def __str__(self):
        return f"{self.book_name} - أصحاح {self.chapter_number} {f'({self.title})' if self.title else ''}"


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")
    text = models.TextField(verbose_name="نص السؤال")
    explanation = models.TextField(blank=True, verbose_name="التفسير")

    # Future-ready: when True, multiple choices can be marked correct
    # UI stays single-select for now — just flip this flag when ready
    allow_multiple_correct = models.BooleanField(default=False, verbose_name="يسمح بأكثر من إجابة صحيحة")

    class Meta:
        ordering = ['order']
        verbose_name = "سؤال"
        verbose_name_plural = "الأسئلة"

    @property
    def correct_choices(self):
        return self.choices.filter(is_correct=True)

    @property
    def first_correct_key(self):
        c = self.choices.filter(is_correct=True).first()
        return c.key if c else None

    def __str__(self):
        return f"{self.quiz} - س{self.order}: {self.text[:40]}"


class QuestionChoice(models.Model):
    """
    Replaces the fixed choice_a/b/c/d fields on Question.
    Supports 2–8 choices per question. Minimum 2 required (a, b).
    is_correct can be True on multiple rows when question.allow_multiple_correct=True.
    """
    CHOICE_KEYS = [
        ('a', 'أ'), ('b', 'ب'), ('c', 'ج'), ('d', 'د'),
        ('e', 'هـ'), ('f', 'و'), ('g', 'ز'), ('h', 'ح'),
    ]

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    key = models.CharField(max_length=1, choices=CHOICE_KEYS, verbose_name="مفتاح الاختيار")
    text = models.CharField(max_length=500, verbose_name="نص الاختيار")
    is_correct = models.BooleanField(default=False, verbose_name="إجابة صحيحة")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")

    class Meta:
        ordering = ['order']
        verbose_name = "اختيار"
        verbose_name_plural = "الاختيارات"
        unique_together = [('question', 'key')]

    def __str__(self):
        return f"{self.question} - {self.key}: {self.text[:30]}"


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
    # Now stores the choice key (a/b/c/d/e/f/g/h)
    selected_choice = models.CharField(max_length=1, verbose_name="الاختيار المحدد")
    is_correct = models.BooleanField(verbose_name="هل الإجابة صحيحة؟")

    class Meta:
        verbose_name = "إجابة سؤال"
        verbose_name_plural = "إجابات الأسئلة"

    def __str__(self):
        return f"إجابة {self.score.user.username} على {self.question}"