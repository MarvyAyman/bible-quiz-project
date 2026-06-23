from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone



class Material(models.Model):

    """

    Unified content record for Bible quizzes, Spiritual Book quizzes,

    and Iqraa chapters. One shared table filtered by `category`.

    """

    CATEGORY_CHOICES = [

        ('bible', 'كتاب مقدس'),

        ('spiritual', 'كتاب روحي'),

        ('iqraa', 'اقرأ واعرف واكسب'),

    ]



    category = models.CharField(

        max_length=20, choices=CATEGORY_CHOICES, default='bible',

        db_index=True, verbose_name="تصنيف المحتوى"

    )

    source_name = models.CharField(max_length=100, verbose_name="اسم السفر / الكتاب")

    chapter_number = models.IntegerField(verbose_name="رقم الأصحاح / الفصل")

    title = models.CharField(max_length=200, blank=True, default='', verbose_name="عنوان فرعي (اختياري)")



    slug = models.SlugField(max_length=250, unique=True, blank=True, allow_unicode=True, verbose_name="رابط الـ Slug")

    is_active = models.BooleanField(default=False, db_index=True, verbose_name="نشط")

    created_at = models.DateTimeField( default=timezone.now, verbose_name="تاريخ الإنشاء")

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        verbose_name = "محتوى"

        verbose_name_plural = "المحتويات"

        ordering = ['category', 'chapter_number']

        indexes = [models.Index(fields=['category', 'is_active'])]



    def save(self, *args, **kwargs):

        if not self.slug:

            prefix_map = {'bible': 'كتاب-مقدس', 'spiritual': 'كتاب-روحي', 'iqraa': 'اقرأ'}

            prefix = prefix_map.get(self.category, 'محتوى')

            base_slug = f"{prefix}-{self.source_name}-الاصحاح-{self.chapter_number}"

            if self.title:

                base_slug += f"-{self.title}"

            self.slug = base_slug.replace(" ", "-")

        super().save(*args, **kwargs)



    @property

    def question_count(self):

        return self.questions.count()



    def __str__(self):

        return f"[{self.get_category_display()}] {self.source_name} - {self.chapter_number}"





class MaterialLink(models.Model):

    """

    Dynamic, unlimited (soft-capped at 8) links per Material — used

    mainly by 'iqraa' category. Each link points to an externally

    hosted file (archive.org in this project's case); only the URL is

    stored here, never the file itself.

    """

    LINK_TYPE_CHOICES = [

        ('summary_pdf', 'ملخص PDF'),

        ('full_pdf', 'الفصل كامل PDF'),

        ('image', 'صورة / إنفوجرافيك'),

        ('podcast', 'بودكاست صوتي'),

    ]



    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='links')

    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES, verbose_name="نوع الرابط")

    url = models.URLField(max_length=500, verbose_name="الرابط")

    label = models.CharField(max_length=150, blank=True, default='', verbose_name="وصف مختصر (اختياري)")

    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")



    class Meta:

        verbose_name = "رابط محتوى"

        verbose_name_plural = "روابط المحتوى"

        ordering = ['order']

        indexes = [models.Index(fields=['material', 'link_type'])]



    def __str__(self):

        return f"{self.material} - {self.get_link_type_display()}"





class Question(models.Model):

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="questions")

    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")

    text = models.TextField(verbose_name="نص السؤال")

    explanation = models.TextField(blank=True, default='', verbose_name="التفسير")

    allow_multiple_correct = models.BooleanField(default=False, verbose_name="يسمح بأكثر من إجابة صحيحة")

    created_at = models.DateTimeField(  default=timezone.now, verbose_name="تاريخ الإنشاء")



    class Meta:

        verbose_name = "سؤال"

        verbose_name_plural = "الأسئلة"

        ordering = ['order']



    @property

    def first_correct_key(self):

        c = self.choices.filter(is_correct=True).first()

        return c.key if c else None



    def __str__(self):

        return f"{self.material.source_name} - {self.text[:40]}"





class QuestionChoice(models.Model):

    CHOICE_KEYS = [

        ('a', 'أ'), ('b', 'ب'), ('c', 'ج'), ('d', 'د'),

        ('e', 'هـ'), ('f', 'و'), ('g', 'ز'), ('h', 'ح'),

    ]



    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")

    key = models.CharField(max_length=1, choices=CHOICE_KEYS, verbose_name="رمز الاختيار")

    text = models.CharField(max_length=500, verbose_name="نص الاختيار")

    is_correct = models.BooleanField(default=False, verbose_name="هل هي الإجابة الصحيحة؟")

    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")



    class Meta:

        verbose_name = "اختيار"

        verbose_name_plural = "الاختيارات"

        ordering = ['order']

        unique_together = [('question', 'key')]



    def __str__(self):

        return f"{self.key}: {self.text[:30]}"





class Score(models.Model):

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scores")

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="scores")

    score_value = models.IntegerField(verbose_name="الدرجة")

    time_taken_seconds = models.IntegerField(verbose_name="الوقت المستغرق بالثواني")

    created_at = models.DateTimeField(  default=timezone.now, verbose_name="تاريخ المحاولة")



    class Meta:

        verbose_name = "نتيجة"

        verbose_name_plural = "النتائج"

        ordering = ['-score_value', 'time_taken_seconds']

        indexes = [models.Index(fields=['material', 'score_value'])]



    def __str__(self):

        return f"{self.user.username} - {self.material} ({self.score_value})"





class QuestionResponse(models.Model):

    score = models.ForeignKey(Score, on_delete=models.CASCADE, related_name="responses")

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="responses")

    selected_choice = models.CharField(max_length=1, verbose_name="الاختيار الذي تم تحديده")

    is_correct = models.BooleanField(verbose_name="هل الحل صحيح؟")



    class Meta:

        verbose_name = "إجابة سؤال"

        verbose_name_plural = "إجابات الأسئلة"



    def __str__(self):

        return f"استجابة {self.score.user.username} لسؤال {self.question_id}"