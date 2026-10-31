from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.utils import timezone


# ---------------------------------------------------------------------------
# Category (dynamic — replaces the old hardcoded CATEGORY_CHOICES)
# ---------------------------------------------------------------------------
class Category(models.Model):
    """
    Dynamic categories (e.g. كتاب مقدس، كتاب روحي، اقرأ واعرف واكسب).
    Managed via the panel — orderable by drag & drop, toggleable active/inactive.
    `has_links` controls whether materials in this category can carry
    external links (PDF / audio / images) or only questions.
    `link_mode` controls whether the admin can add a single link or multiple
    links per material (only relevant when `has_links=True`).
    """

    LINK_MODE_CHOICES = [
        ('multiple', 'روابط متعددة'),
        ('single',   'رابط واحد فقط'),
    ]

    key = models.SlugField(
        max_length=50, unique=True, allow_unicode=True,
        verbose_name="المعرف (key)",
        help_text="معرّف ثابت بالإنجليزية يُستخدم داخلياً، مثال: bible",
    )
    name = models.CharField(max_length=100, verbose_name="اسم التصنيف")
    label = models.CharField(
        max_length=150, blank=True, default='',
        verbose_name="الاسم المعروض (اختياري)",
        help_text="لو تركتيه فارغاً سيُستخدم الاسم أعلاه",
    )
    icon = models.CharField(
        max_length=20, blank=True, default='📁',
        verbose_name="الأيقونة (إيموجي)",
    )

    has_links = models.BooleanField(
        default=True,
        verbose_name="يدعم إضافة روابط",
        help_text="عند التعطيل، لن يتمكن المشرف من إضافة روابط للمواد في هذا التصنيف ولن تظهر للمشتركين.",
    )

    link_mode = models.CharField(
        max_length=10,
        choices=LINK_MODE_CHOICES,
        default='multiple',
        verbose_name="طريقة عرض الروابط",
        help_text="يُستخدم فقط عندما يكون خيار الروابط مفعّلاً.",
    )
    
    chapter_number_optional = models.BooleanField(
        default=False,
        verbose_name="رقم الأصحاح اختياري",
        help_text="عند التفعيل، يمكن إضافة مادة في هذا التصنيف بدون إدخال رقم الأصحاح / الفصل.",
    )

    has_timer = models.BooleanField(
        default=False,
        verbose_name="تمكين المؤقت الزمني",
        help_text="عند التفعيل، تظهر ساعة عدّ تنازلي في صفحة المسابقة لهذا التصنيف.",
    )
    
    order = models.PositiveIntegerField(default=0, db_index=True, verbose_name="الترتيب")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="نشط")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "تصنيف"
        verbose_name_plural = "التصنيفات"
        ordering = ['order', 'id']

    def save(self, *args, **kwargs):
        if self._state.adding and not self.order:
            last = Category.objects.aggregate(m=models.Max('order'))['m'] or 0
            self.order = last + 1
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.label or self.name

    @property
    def display_label(self):
        return f"{self.icon} {self.display_name}".strip()

    def __str__(self):
        return self.display_name


# ---------------------------------------------------------------------------
# Material (unified content record)
# ---------------------------------------------------------------------------
class Material(models.Model):
    """
    Unified content record for Bible quizzes, Spiritual Book quizzes,
    and Iqraa chapters. One shared table filtered by `category`.
    """
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='materials',
        null=True, blank=True,
        verbose_name="تصنيف المحتوى",
    )
    source_name = models.CharField(max_length=100, verbose_name="اسم السفر / الكتاب")
    chapter_number = models.IntegerField(
        null=True, blank=True,
        verbose_name="رقم الأصحاح / الفصل",
    )
    title = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name="عنوان فرعي (اختياري)",
    )

    slug = models.SlugField(
        max_length=250, unique=True, blank=True, allow_unicode=True,
        verbose_name="رابط الـ Slug",
    )
    is_active = models.BooleanField(default=False, db_index=True, verbose_name="نشط")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الإنشاء")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "محتوى"
        verbose_name_plural = "المحتويات"
        ordering = ['category__order', 'chapter_number']   # 👈 FIXED
        indexes = [models.Index(fields=['category', 'is_active'])]  # 👈 FIXED

    def save(self, *args, **kwargs):
        if not self.slug:
            prefix = self.category.key if self.category_id else 'محتوى'
            if self.chapter_number is not None:
                chapter_part = f"-الاصحاح-{self.chapter_number}"
            else:
                chapter_part = ""
            base_slug = f"{prefix}-{self.source_name}{chapter_part}"
            if self.title:
                base_slug += f"-{self.title}"
            self.slug = base_slug.replace(" ", "-")
        super().save(*args, **kwargs)

    @property
    def question_count(self):
        return self.questions.count()

    def __str__(self):
        chap = self.chapter_number if self.chapter_number is not None else "—"
        return f"[{self.category.display_name}] {self.source_name} - {chap}"

# ---------------------------------------------------------------------------
# MaterialLink
# ---------------------------------------------------------------------------
class MaterialLink(models.Model):
    """
    Dynamic links per Material — used mainly by categories with `has_links=True`.
    If `category.link_mode == 'single'`, only one link is allowed per material.
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


# ---------------------------------------------------------------------------
# Question
# ---------------------------------------------------------------------------
class Question(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField(default=0, verbose_name="الترتيب")
    text = models.TextField(verbose_name="نص السؤال")
    explanation = models.TextField(blank=True, default='', verbose_name="التفسير")
    allow_multiple_correct = models.BooleanField(default=False, verbose_name="يسمح بأكثر من إجابة صحيحة")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الإنشاء")

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


# ---------------------------------------------------------------------------
# QuestionChoice
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------
class Score(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scores")
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="scores")
    score_value = models.IntegerField(verbose_name="الدرجة")
    time_taken_seconds = models.IntegerField(verbose_name="الوقت المستغرق بالثواني")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ المحاولة")

    class Meta:
        verbose_name = "نتيجة"
        verbose_name_plural = "النتائج"
        ordering = ['-score_value', 'time_taken_seconds']
        indexes = [models.Index(fields=['material', 'score_value'])]

    def __str__(self):
        return f"{self.user.username} - {self.material} ({self.score_value})"


# ---------------------------------------------------------------------------
# QuestionResponse
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------
class Badge(models.Model):
    CONDITION_CHOICES = [
        ('quiz_completion_count', 'عدد مسابقات مكتملة'),
        ('perfect_score_count', 'عدد مرات الحصول على الدرجة الكاملة'),
        ('category_completion_count', 'عدد مسابقات مكتملة من تصنيف معين'),
        ('streak_days', 'أيام متتالية'),
    ]

    name = models.CharField(max_length=100, verbose_name="اسم الدرع")
    description = models.TextField(verbose_name="وصف الشرط")
    icon_image_url = models.URLField(max_length=500, blank=True, default='', verbose_name="رابط صورة الدرع")
    condition_type = models.CharField(max_length=30, choices=CONDITION_CHOICES, verbose_name="نوع الشرط")
    threshold_value = models.PositiveIntegerField(verbose_name="القيمة المطلوبة")

    # category_filter = models.ForeignKey(
    #     Category, on_delete=models.SET_NULL, null=True, blank=True,
    #     related_name='badges', verbose_name="تصنيف المحتوى (اختياري)",
    # )
    
    category_filter = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='badges', verbose_name="تصنيف المحتوى (اختياري)")

    is_active = models.BooleanField(default=True, verbose_name="الدرع نشط")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "درع"
        verbose_name_plural = "الدروع"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# UserBadge
# ---------------------------------------------------------------------------
class UserBadge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="badges")
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name="users_earned")
    earned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "درع مشترك"
        verbose_name_plural = "دروع المشتركين"
        unique_together = [('user', 'badge')]

    def __str__(self):
        return f"{self.user.username} - {self.badge.name}"


# ---------------------------------------------------------------------------
# ActivityComment
# ---------------------------------------------------------------------------
class ActivityComment(models.Model):
    """
    نظام تعليقات مرن ونامي: يسمح بالتعليق على النتيجة (Score) أو على الأوسمة (UserBadge)
    دون تعديل جداولهم الأصلية.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activity_comments", verbose_name="المعلق")
    text = models.TextField(verbose_name="نص التعليق")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ التعليق")

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = "تعليق النشاط"
        verbose_name_plural = "تعليقات الأنشطة"
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username}: {self.text[:30]}"


# ---------------------------------------------------------------------------
# ActivityReaction
# ---------------------------------------------------------------------------
class ActivityReaction(models.Model):
    """
    نظام تفاعلات (إيموجي) مرن: يدعم محاكاة فيسبوك بوضع تفاعل واحد فقط لكل مستخدم على البوست.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activity_reactions", verbose_name="المتفاعل")
    emoji = models.CharField(max_length=10, verbose_name="الإيموجي المستعمل")
    label = models.CharField(max_length=20, verbose_name="اسم التفاعل (مبارك، آمين...)")
    created_at = models.DateTimeField(default=timezone.now)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = "تفاعل النشاط"
        verbose_name_plural = "تفاعلات الأنشطة"
        unique_together = ('user', 'content_type', 'object_id')

    def __str__(self):
        return f"{self.user.username} -> {self.emoji}"