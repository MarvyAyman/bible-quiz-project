from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.db.models import Avg, Count
from django.utils.text import slugify
from django.conf import settings
from .models import Material, MaterialLink, Question, QuestionChoice, Score, QuestionResponse
import json
import re
import os
import requests
import jwt
from urllib.parse import unquote
from django.views.decorators.csrf import csrf_exempt
from django.db.models.functions import TruncDate
from .models import Material, Score, Badge, UserBadge
import uuid
import datetime

ALL_CHOICE_KEYS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
CHOICE_KEY_LABELS = {'a': 'أ', 'b': 'ب', 'c': 'ج', 'd': 'د', 'e': 'هـ', 'f': 'و', 'g': 'ز', 'h': 'ح'}

CATEGORY_LABELS = {
    'bible': '📖 كتاب مقدس',
    'spiritual': '📚 كتاب روحي',
    'iqraa': '📁 اقرأ واعرف واكسب',
}


def decode_url_slug(url_string):
    return unquote(url_string)


# ---------------------------------------------------------------------------
# Public / subscriber views (الواجهة العامة للمشتركين)
# ---------------------------------------------------------------------------

def index_view(request):
    """الصفحة الرئيسية للمشتركين مع دعم أزرار الفلترة للأقسام المتاحة"""
    category_filter = request.GET.get('category', 'all')
    
    # جلب المواد المنشورة والنشطة فقط للمشتركين
    all_active_materials = Material.objects.filter(is_active=True).order_by('-created_at')

    # حساب الأعداد لكل قسم ديناميكياً لإظهارها فوق أزرار الفلترة
    counts = {
        'all': all_active_materials.count(),
        'bible': all_active_materials.filter(category='bible').count(),
        'spiritual': all_active_materials.filter(category='spiritual').count(),
        'iqraa': all_active_materials.filter(category='iqraa').count(),
    }

    # تطبيق الفلترة بناءً على التبويب المختار
    if category_filter != 'all':
        materials = all_active_materials.filter(category=category_filter)
    else:
        materials = all_active_materials

    return render(request, 'quiz/index.html', {
        'materials': materials,
        'category_filter': category_filter,
        'counts': counts,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    })


def quiz_view(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug, is_active=True)
    questions_data = []
    
    for q in material.questions.prefetch_related('choices').all():
        choices = [{'key': c.key, 'text': c.text} for c in q.choices.all()]
        questions_data.append({
            'id': q.id,
            'text': q.text,
            'choices': choices,
            'correct': next((c.key for c in q.choices.all() if c.is_correct), 'a'),
            'explanation': q.explanation,
        })

    context = {
        'material': material,
        'links': material.links.all(),  # جلب الروابط الديناميكية المرفقة بالمادة
        'questions_data': questions_data,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
    return render(request, 'quiz/quiz_detail.html', context)


# 🔐 بيانات اعتماد Archive.org الخاصة بكِ
IA_ACCESS_KEY = "L8yZpkLVeZkbYdXX"
IA_SECRET_KEY = "XNtm6xCJXtFfOiFA"

def manage_badges(request):
    badges = Badge.objects.all().order_by('-id')
    counts = {b.id: b.users_earned.count() for b in badges}
    
    return render(request, 'quiz/panel/manage_badges.html', {
        'badges': badges,
        'counts': counts,
        'active': 'manage_badges'
    })

def badge_create(request):
    if request.method == 'POST':
        b = Badge.objects.create(
            name=request.POST.get('name'),
            description=request.POST.get('description'),
            icon_image_url=request.POST.get('icon_image_url', ''),
            condition_type=request.POST.get('condition_type'),
            threshold_value=int(request.POST.get('threshold_value', 1)),
            category_filter=request.POST.get('category_filter', ''),
            is_active='is_active' in request.POST
        )
        return redirect('manage_badges')
        
    context = {
        'condition_types': Badge.CONDITION_CHOICES,
        'category_choices': [('', 'كل التصنيفات')] + Material.CATEGORY_CHOICES,
        'form_data': {'is_active': True}
    }
    return render(request, 'quiz/panel/badge_form.html', context)

@csrf_exempt
def badge_edit(request, badge_id):
    """
    تعديل بيانات الدرع مع التحقق الإجباري من اختيار التصنيف بناءً على نوع القاعدة.
    """
    badge_instance = get_object_or_404(Badge, id=badge_id)
    error = None
    

    if request.method == 'POST':
        condition_type = request.POST.get('condition_type')
        category_filter = request.POST.get('category_filter', '').strip()
        
        # 💡 تم حذف شرط المعارضة الصارم لكي يقبل الحفظ بدون تصنيف بنجاح!
        badge_instance.name = request.POST.get('name')
        badge_instance.description = request.POST.get('description')
        badge_instance.icon_image_url = request.POST.get('icon_image_url', '')
        badge_instance.condition_type = condition_type
        badge_instance.threshold_value = int(request.POST.get('threshold_value', 1))
        
        # إذا كانت القاعدة أيام متتالية، نفرغ التصنيف تلقائياً، وغير ذلك نحفظه كما هو (سواء اخترتِ تصنيف أو تركتيه فارغاً)
        badge_instance.category_filter = category_filter if condition_type != 'streak_days' else ''
        badge_instance.is_active = 'is_active' in request.POST
        
        badge_instance.save()
        return redirect('manage_badges')

    form_data = {
        'name': badge_instance.name,
        'description': badge_instance.description,
        'icon_image_url': badge_instance.icon_image_url,
        'condition_type': badge_instance.condition_type,
        'threshold_value': badge_instance.threshold_value,
        'category_filter': badge_instance.category_filter,
        'is_active': badge_instance.is_active
    }

    context = {
        'badge': badge_instance,
        'condition_types': Badge.CONDITION_CHOICES,
        'category_choices': [('', 'اختر التصنيف المستهدف...')] + Material.CATEGORY_CHOICES,
        'form_data': form_data,
        'error': error
    }
    return render(request, 'quiz/panel/badge_form.html', context)

@require_POST
def badge_delete(request, badge_id):
    """
    حذف الدرع نهائياً من النظام ومن سجلات جميع المشتركين الذين حصلوا عليه.
    """
    badge_instance = get_object_or_404(Badge, id=badge_id)
    badge_instance.delete()
    return redirect('manage_badges')

@require_POST
def badge_toggle(request, badge_id):
    """
    تغيير حالة الدرع سرياً بين التفعيل والتعطيل (Active / Inactive)
    دون الحاجة للدخول لصفحة التعديل الكاملة.
    """
    badge_instance = get_object_or_404(Badge, id=badge_id)
    
    # عكس القيمة الحالية بذكاء
    badge_instance.is_active = not badge_instance.is_active
    badge_instance.save()
    
    return redirect('manage_badges')

@csrf_exempt
def upload_badge_image_api(request):
    """
    استقبال الصورة عبر AJAX من السحب والإفلات أو اللصق،
    ورفعها الفوري إلى Archive.org S3 API وإعادة الرابط المباشر.
    """
    if request.method != 'POST' or not request.FILES.get('badge_file'):
        return JsonResponse({'status': 'error', 'message': 'ملف غير صالحة أو طلب خاطئ'}, status=400)
    
    image_file = request.FILES['badge_file']
    
    # توليد اسم عشوائي فريد للـ Bucket والملف لعدم حدوث تعارض في خوادم archive
    unique_id = uuid.uuid4().hex[:10]
    bucket_name = f"quiz_badge_assets_{unique_id}"
    file_ext = os.path.splitext(image_file.name)[1] or '.png'
    target_filename = f"badge_{unique_id}{file_ext}"
    
    # الرابط النهائي المتوقع على Archive.org
    archive_url = f"https://archive.org/download/{bucket_name}/{target_filename}"
    archive_s3_endpoint = f"https://s3.us.archive.org/{bucket_name}/{target_filename}"
    
    try:
        # قراءة محتوى الصورة المرفوعة مؤقتاً
        file_data = image_file.read()
        
        # تجهيز ترويسة الطلب لـ Archive S3 API
        headers = {
            "Authorization": f"LOW {IA_ACCESS_KEY}:{IA_SECRET_KEY}",
            "Content-Type": image_file.content_type,
            "x-archive-auto-make-bucket": "1", # إنشاء الـ Bucket تلقائياً إن لم يتواجد
        }
        
        # إرسال الصورة بواسطة PUT request
        response = requests.put(archive_s3_endpoint, data=file_data, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return JsonResponse({
                'status': 'success',
                'url': archive_url
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': f"فشل الرفع لـ Archive.org كود الخطأ: {response.status_code}"
            }, status=500)
            
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f"حدث خطأ أثناء الاتصال: {str(e)}"}, status=500)

@csrf_exempt
@require_POST
def submit_score(request, quiz_slug):
    """
    استقبال وحفظ نتيجة محاولة المشترك بالكامل، وفحص الدروع المكتسبة تلقائياً،
    وإلغاء التوجيه لصفحة الـ leaderboard.html الملقاة نهائياً.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'عفواً، طلب غير مسموح.'}, status=400)
    
    # 1. فك تشفير السلوج وجلب المسابقة / المادة المطلوبة
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)
    
    # 2. الحصول على بيانات المشترك والنتيجة والوقت من الطلب (Request)
    # ملاحظة: يمكنكِ تعديل هذا الجزء ليطابق طريقة سحب المستخدم الحالي (سواء عبر Supabase session أو request.user)
    user = request.user 
    if not user.is_authenticated:
        # إذا كنتِ تعتمدين على التحقق عبر التوكن أو البيانات القادمة من AJAX
        return JsonResponse({'status': 'error', 'message': 'يجب تسجيل الدخول لحفظ النتيجة.'}, status=401)

    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        score_value = int(data.get('score_value', 0))
        time_taken_seconds = int(data.get('time_taken_seconds', 0))
        
    except (ValueError, TypeError, json.JSONDecodeError):        return JsonResponse({'status': 'error', 'message': 'بيانات النتيجة غير صالحة.'}, status=400)

    # 3. حفظ كائن النتيجة في قاعدة البيانات
    score = Score.objects.create(
        user=user,
        material=material,
        score_value=score_value,
        time_taken_seconds=time_taken_seconds
    )

    # 4. معالجة حفظ الإجابات التفصيلية للأسئلة (Question Responses) إن وجدت في طلبكِ
    # [هنا يوضع كائن حفظ تفاصيل الإجابات إذا كنتِ تستخدمينه]

    # 5. 🏅 فحص الدروع النشطة (Automated Badge Engine)
    new_earned_badges = []
    
    # جلب جميع الدروع المفعلة التي لم يسبق للمستخدم كسبها حتى الآن
    active_badges = Badge.objects.filter(is_active=True)
    already_earned_ids = UserBadge.objects.filter(user=user).values_list('badge_id', flat=True)
    
    for badge in active_badges:
        if badge.id in already_earned_ids:
            continue  # المشترك يمتلك هذا الدرع بالفعل، تخطى للفحص التالي
            
        is_eligible = False
        
        # النوع أ: عدد المسابقات المكتملة (Quiz Completion Count)
        if badge.condition_type == 'quiz_completion_count':
            qs = Score.objects.filter(user=user)
            if badge.category_filter:
                qs = qs.filter(material__category=badge.category_filter)
            # حساب عدد المواد الفريدة والمختلفة التي دخلها المشترك بنجاح
            completed_count = qs.values('material').distinct().count()
            if completed_count >= badge.threshold_value:
                is_eligible = True
                
        # النوع ب: عدد المحاولات ذات الدرجات الكاملة النهائية (Perfect Score Count)
        elif badge.condition_type == 'perfect_score_count':
            qs = Score.objects.filter(user=user)
            if badge.category_filter:
                qs = qs.filter(material__category=badge.category_filter)
            
            # مقارنة درجة المحاولة مع إجمالي عدد أسئلة المادة المقترنة بها
            perfect_count = 0
            for s in qs.select_related('material'):
                total_questions = s.material.questions.count()
                if total_questions > 0 and s.score_value == total_questions:
                    perfect_count += 1
                    
            if perfect_count >= badge.threshold_value:
                is_eligible = True
                
        # النوع ج: عدد الأيام المتتالية لحل المسابقات (Streak Days)
        elif badge.condition_type == 'streak_days':
            # جلب التواريخ الفريدة المرتبة تنازلياً للمحاولات التي قام بها العضو
            dates = Score.objects.filter(user=user)\
                                 .annotate(date=TruncDate('created_at'))\
                                 .values_list('date', flat=True)\
                                 .distinct()\
                                 .order_by('-date')
            streak = 0
            if dates.exists():
                today = datetime.date.today()
                # التحقق من أن أحدث محاولة كانت اليوم أو بالأمس للحفاظ على السلسلة نشطة
                if dates[0] in [today, today - datetime.timedelta(days=1)]:
                    streak = 1
                    check_date = dates[0]
                    for d in dates[1:]:
                        if check_date - d == datetime.timedelta(days=1):
                            streak += 1
                            check_date = d
                        elif check_date == d:
                            continue  # محاولة أخرى في نفس اليوم، تخطى وحافظ على الاستمرارية
                        else:
                            break  # انقطعت السلسلة المتتالية
            if streak >= badge.threshold_value:
                is_eligible = True

        # إذا استوفى الشروط بنجاح، سجل الدرع فوراً للعضو وأضفه لمصفوفة العرض الخارجي
        if is_eligible:
            UserBadge.objects.create(user=user, badge=badge)
            new_earned_badges.append({
                'id': badge.id,
                'name': badge.name,
                'description': badge.description,
                'icon': badge.icon_image_url or "https://cdn-icons-png.flaticon.com/512/6188/6188595.png"
            })

    # 6. الرد النهائي بنظام JSON التفاعلي (بدون أي توجيه لملف leaderboard.html المحذوف)
    # نوجه العضو للرئيسية أو صفحة قائمة القسم المناسب بناءً على التصنيف ليرى إنجازاته
    category_urls = {
        'bible': reverse('bible_list'),
        'spiritual': reverse('spiritual_list'),
        'iqraa': reverse('iqraa_list'),
    }
    redirect_destination = category_urls.get(material.category, reverse('index'))

    return JsonResponse({
        'status': 'success',
        'message': 'تم حفظ النتيجة بنجاح وفحص سجل أوسمتكِ الجارية.',
        'score_id': score.id,
        'score_value': score_value,
        'redirect_url': redirect_destination,  # 👈 يتم التوجيه للموقع/القسم مباشرة في الـ JavaScript
        'new_badges': new_earned_badges        # 👈 مصفوفة الدروع المكتسبة حديثاً لعرض تهنئة منبثقة ممتازة للمشترك
    })
    
# def leaderboard_view(request, quiz_slug):
#     quiz_slug = unquote(quiz_slug)
#     material = get_object_or_404(Material, slug=quiz_slug)

#     current_user_uid = request.GET.get('uid', '')  

#     seen_users = set()
#     all_ranked = []

#     for score in Score.objects.filter(material=material).select_related('user').order_by('-score_value', 'time_taken_seconds'):
#         if score.user_id not in seen_users:
#             seen_users.add(score.user_id)
#             minutes = score.time_taken_seconds // 60
#             seconds = score.time_taken_seconds % 60
#             score.formatted_time = f"{minutes:02d}:{seconds:02d}"
#             all_ranked.append(score)

#     top_scores = all_ranked[:10]

#     current_user_rank = None
#     current_user_score = None
#     current_user_time = None
#     current_user_name = None

#     if current_user_uid:
#         for idx, score in enumerate(all_ranked):
#             if score.user.username == current_user_uid:
#                 rank = idx + 1
#                 if rank > 10:
#                     current_user_rank = rank
#                     current_user_score = score.score_value
#                     current_user_time = score.formatted_time
#                     current_user_name = score.user.first_name if score.user.first_name else score.user.username
#                 break

#     return render(request, 'quiz/leaderboard.html', {
#         'material': material,
#         'leaderboard': top_scores,
#         'current_user_uid': current_user_uid,
#         'current_user_rank': current_user_rank,
#         'current_user_score': current_user_score,
#         'current_user_time': current_user_time,
#         'current_user_name': current_user_name,
#     })


def materials_list_client(request, category):
    """عرض قائمة المحتوى النشط للجمهور (المشتركين) بناءً على التصنيف"""
    materials = Material.objects.filter(is_active=True, category=category).order_by('source_name', 'chapter_number')
    category_title = CATEGORY_LABELS.get(category, "قائمة المسابقات")
    
    return render(request, 'quiz/materials_list.html', {
        'materials': materials,
        'category': category,
        'category_title': category_title
    })


# ---------------------------------------------------------------------------
# Text -> quiz structure parser (المفسر الخلفي الاختياري للملفات)
# ---------------------------------------------------------------------------

ARABIC_LETTER_TO_KEY = {'ا': 'a', 'أ': 'a', 'ب': 'b', 'ج': 'c', 'د': 'd'}
QUESTION_RE = re.compile(r'^\s*\d+\s*[-–.)]\s*(.+)$')
CHOICE_RE = re.compile(r'^\s*([اأبجد])\s*[-–.]\s*(.+)$')
ANSWER_RE = re.compile(r'^\s*ج\s*:\s*([اأبجد])\s*$')
EXPLANATION_RE = re.compile(r'^\s*(?:التفسير|تفسير)\s*:\s*(.*)$')


def _finalize_question(question):
    raw_choices = question['choices']
    question['choices'] = [
        {'key': key, 'label': CHOICE_KEY_LABELS[key], 'value': raw_choices.get(key, '')}
        for key in ['a', 'b', 'c', 'd']
        if raw_choices.get(key, '').strip()
    ]
    existing_keys = [c['key'] for c in question['choices']]
    for key in ['a', 'b']:
        if key not in existing_keys:
            idx = 0 if key == 'a' else min(1, len(question['choices']))
            question['choices'].insert(idx, {
                'key': key, 'label': CHOICE_KEY_LABELS[key], 'value': ''
            })
    return question


def parse_quiz_text(raw_text):
    questions = []
    current = None
    collecting = None

    for raw_line in (raw_text or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue

        q_match = QUESTION_RE.match(line)
        ans_match = ANSWER_RE.match(line)
        exp_match = EXPLANATION_RE.match(line)
        c_match = CHOICE_RE.match(line)

        if q_match:
            if current:
                questions.append(_finalize_question(current))
            current = {
                'order': len(questions) + 1,
                'text': q_match.group(1).strip(),
                'choices': {'a': '', 'b': '', 'c': '', 'd': ''},
                'correct': 'a',
                'explanation': '',
            }
            collecting = 'text'
            continue

        if current is None:
            continue

        if ans_match:
            current['correct'] = ARABIC_LETTER_TO_KEY[ans_match.group(1)]
            collecting = None
        elif exp_match:
            current['explanation'] = exp_match.group(1).strip()
            collecting = 'explanation'
        elif c_match:
            key = ARABIC_LETTER_TO_KEY[c_match.group(1)]
            current['choices'][key] = c_match.group(2).strip()
            collecting = f'choice:{key}'
        elif collecting == 'text':
            current['text'] += ' ' + line
        elif collecting == 'explanation':
            current['explanation'] += ' ' + line
        elif collecting and collecting.startswith('choice:'):
            ckey = collecting.split(':')[1]
            current['choices'][ckey] += ' ' + line

    if current:
        questions.append(_finalize_question(current))
    return questions


def extract_text_from_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith('.docx'):
        import docx
        document = docx.Document(uploaded_file)
        return '\n'.join(p.text for p in document.paragraphs)
    return uploaded_file.read().decode('utf-8', errors='ignore')


# ---------------------------------------------------------------------------
# Panel / Dashboard (staff-only) views (لوحة التحكم والإدارة)
# ---------------------------------------------------------------------------

"""
panel_dashboard view — replace the existing panel_dashboard function in views.py
with this updated version. All other views remain unchanged.

New data provided to the template:
  • category_stats   — per-category breakdown (bible / spiritual / iqraa)
  • top_performers   — top 5 users by total correct answers
  • recent_activity  — last 7 Score records for the "live feed" section
  • engagement_trend — daily attempt counts for the last 7 days (for the trend sparkline)
  • hardest_questions — same as before, now also carries category info
  • active_materials_count / draft_materials_count
"""

from django.contrib.auth.models import User
from django.db.models import Avg, Count, Sum, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
import datetime

from .models import Material, Question, Score, QuestionResponse


def panel_dashboard(request):
    # ── 1. Global KPI cards ────────────────────────────────────────────────
    total_subscribers = User.objects.filter(is_staff=False).count()
    total_attempts    = Score.objects.count()

    avg_time_seconds  = Score.objects.aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0
    minutes = int(avg_time_seconds // 60)
    seconds = int(avg_time_seconds % 60)
    avg_time_formatted = f"{minutes:02d}:{seconds:02d}"

    overall_correct = QuestionResponse.objects.filter(is_correct=True).count()
    overall_total   = QuestionResponse.objects.count()
    overall_avg_percentage = round((overall_correct / overall_total * 100)) if overall_total else 0

    active_materials_count = Material.objects.filter(is_active=True).count()
    draft_materials_count  = Material.objects.filter(is_active=False).count()

    # ── 2. Per-category stats (for the category breakdown cards) ──────────
    CATEGORIES = [
        ('bible',    '📖 كتاب مقدس'),
        ('spiritual','📚 كتاب روحي'),
        ('iqraa',    '📁 اقرأ واعرف واكسب'),
    ]
    category_stats = []
    for cat_key, cat_label in CATEGORIES:
        mat_ids = Material.objects.filter(category=cat_key).values_list('id', flat=True)
        cat_attempts = Score.objects.filter(material_id__in=mat_ids).count()
        cat_correct  = QuestionResponse.objects.filter(
            question__material__category=cat_key, is_correct=True
        ).count()
        cat_total    = QuestionResponse.objects.filter(
            question__material__category=cat_key
        ).count()
        cat_avg_pct  = round((cat_correct / cat_total * 100)) if cat_total else 0
        cat_mat_count = Material.objects.filter(category=cat_key, is_active=True).count()
        category_stats.append({
            'key':       cat_key,
            'label':     cat_label,
            'attempts':  cat_attempts,
            'avg_pct':   cat_avg_pct,
            'mat_count': cat_mat_count,
        })

    # ── 3. Materials table (all materials, enriched) ───────────────────────
    materials = list(Material.objects.all().order_by('category', 'chapter_number'))
    for m in materials:
        m.attempts     = Score.objects.filter(material=m).count()
        m.num_questions = m.questions.count()

        m_avg_time = Score.objects.filter(material=m).aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0
        m.avg_time_formatted = f"{int(m_avg_time // 60):02d}:{int(m_avg_time % 60):02d}"

        m_correct   = QuestionResponse.objects.filter(question__material=m, is_correct=True).count()
        m_total_resp = QuestionResponse.objects.filter(question__material=m).count()
        m.avg_percentage = round((m_correct / m_total_resp * 100)) if m_total_resp else None
        m.avg_score      = Score.objects.filter(material=m).aggregate(avg=Avg('score_value'))['avg']
        m.book_name      = m.source_name   # alias used in existing template
        m.chapter_number_display = m.chapter_number

    # ── 4. Hardest questions ───────────────────────────────────────────────
    hardest_qs = (
        QuestionResponse.objects
        .filter(is_correct=False)
        .values(
            'question_id',
            'question__text',
            'question__material__source_name',
            'question__material__chapter_number',
            'question__material__category',
        )
        .annotate(wrong_count=Count('id'))
        .order_by('-wrong_count')[:5]
    )
    for hq in hardest_qs:
        total_for_q = QuestionResponse.objects.filter(question_id=hq['question_id']).count()
        hq['wrong_percentage'] = round((hq['wrong_count'] / total_for_q * 100)) if total_for_q else 0
        hq['question_short']   = hq['question__text'][:65] + ('...' if len(hq['question__text']) > 65 else '')

    # ── 5. Top performers (top 5 users by total correct responses) ─────────
    top_performers = (
        QuestionResponse.objects
        .filter(is_correct=True)
        .values('score__user__first_name', 'score__user__username')
        .annotate(correct_total=Count('id'))
        .order_by('-correct_total')[:5]
    )

    # ── 6. Recent activity feed (last 8 quiz attempts) ─────────────────────
    recent_activity = (
        Score.objects
        .select_related('user', 'material')
        .order_by('-created_at')[:8]
    )
    for s in recent_activity:
        total_q = s.material.questions.count()
        s.percentage = round((s.score_value / total_q * 100)) if total_q else 0
        mins, secs = divmod(s.time_taken_seconds, 60)
        s.time_label = f"{mins:02d}:{secs:02d}"
        s.display_name = s.user.first_name or s.user.username[:12]

    # ── 7. New subscribers per day — last 7 days ──────────────────────────
    today = timezone.now().date()
    seven_days_ago = today - datetime.timedelta(days=6)
    daily_counts_qs = (
        User.objects
        .filter(is_staff=False, date_joined__date__gte=seven_days_ago)
        .annotate(day=TruncDate('date_joined'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    # Build a complete 7-day list (0 for missing days)
    daily_map = {row['day']: row['count'] for row in daily_counts_qs}
    ARABIC_DAYS = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
    engagement_trend = []
    for i in range(7):
        d = seven_days_ago + datetime.timedelta(days=i)
        engagement_trend.append({
            'label': ARABIC_DAYS[d.weekday() % 7],  # weekday(): Mon=0 → Sun=6
            'count': daily_map.get(d, 0),
        })

    # ── 8. Chart data for JS ───────────────────────────────────────────────
    # Per-material bar chart (same as before)
    chart_materials = [m for m in materials if m.attempts > 0]

    context = {
        # KPIs
        'total_subscribers':       total_subscribers,
        'total_attempts':          total_attempts,
        'avg_time_formatted':      avg_time_formatted,
        'overall_avg_percentage':  overall_avg_percentage,
        'active_materials_count':  active_materials_count,
        'draft_materials_count':   draft_materials_count,
        # Sections
        'category_stats':          category_stats,
        'materials':               materials,
        'chart_materials':         chart_materials,
        'hardest_questions':       hardest_qs,
        'top_performers':          top_performers,
        'recent_activity':         recent_activity,
        'engagement_trend':        engagement_trend,
        'active':                  'dashboard',
    }
    return render(request, 'quiz/panel/dashboard.html', context)

def manage_materials(request):
    """عرض جدول إدارة كل المواد المرفوعة مع الفلترة الذكية"""
    category = request.GET.get('category', 'all')
    if category and category != 'all':
        materials = Material.objects.filter(category=category).order_by('-id')
    else:
        materials = Material.objects.all().order_by('-id')
        
    counts = {
        'all': Material.objects.count(),
        'bible': Material.objects.filter(category='bible').count(),
        'spiritual': Material.objects.filter(category='spiritual').count(),
        'iqraa': Material.objects.filter(category='iqraa').count(),
    }
    
    return render(request, 'quiz/panel/manage_materials.html', {
        'materials': materials,
        'current_category': category,
        'counts': counts,
        'active': 'manage_materials',
    })


def delete_material(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)
    material.delete()
    return redirect('manage_materials')


@csrf_exempt
@require_POST
def material_publish_toggle(request, quiz_slug):
    """تغيير حالة نشر المحتوى فورياً (نشط / مسودة) من جدول إدارة المواد بـ POST"""
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)
    action = request.POST.get('action')
    
    if action == 'publish':
        material.is_active = True
    elif action == 'unpublish':
        material.is_active = False
        
    material.save()
    return redirect('manage_materials')


# ---------------------------------------------------------------------------
# Unified Create & Edit Material View Flow
# ---------------------------------------------------------------------------


def create_material_step1(request, quiz_slug=None):
    """
    الـ View المدمج والذكي لإنشاء وتعديل المسابقات (صفحة واحدة - Preview Tabs).
    يتعرف تلقائياً على القسم النشط عبر الـ GET Parameter ومثبت الجافاسكريبت بالـ Template.
    """
    material = None
    questions_json = []
    existing_links = []

    # 1. حالة التعديل: إذا قمنا بتمرير الـ slug للمادة
    if quiz_slug:
        quiz_slug = unquote(quiz_slug)
        material = get_object_or_404(Material, slug=quiz_slug)
        category = material.category
        existing_links = material.links.all()
        
        # تجهيز الأسئلة الحالية بصيغة JSON لإعادة حقنها في الـ Form المدمج
        for q in material.questions.prefetch_related('choices').all():
            choices_dict = {c.key: c.text for c in q.choices.all()}
            correct_choice = next((c.key for c in q.choices.all() if c.is_correct), 'a')
            questions_json.append({
                'text': q.text,
                'explanation': q.explanation,
                'correct': correct_choice,
                'choices': choices_dict
            })
    else:
        # 2. حالة إنشاء جديد: التقاط الفئة الافتراضية
        category = request.GET.get('category', 'bible').strip()

    # 3. حفظ ومعالجة البيانات عند الـ Submit للـ Form
    if request.method == 'POST':
        source_name = request.POST.get('source_name', '').strip()
        try:
            chapter_number = int(request.POST.get('chapter_number', 1))
        except ValueError:
            chapter_number = 1
        title = request.POST.get('title', '').strip()

        if not material:
            material = Material(category=category)
            material.is_active = False  # always starts as a draft on first creation
        # NOTE: when editing an existing material, is_active is intentionally
        # left untouched here. Publishing/unpublishing only ever happens on
        # the dedicated publish page (create_material_publish), never as a
        # side-effect of saving questions/metadata here.

        material.source_name = source_name
        material.chapter_number = chapter_number
        material.title = title

        # 🟢 تركيب الـ Slug الجديد المخصص (الاسم - الاصحاح - الرقم - العنوان)
        # نقوم بدمج النصوص أولاً
        if title:
            slug_text = f"{source_name} الاصحاح {chapter_number} {title}"
        else:
            slug_text = f"{source_name} الاصحاح {chapter_number}"
            
        # تحويل النص المدمج إلى سبيكة روابط (Slug) تدعم اللغة العربية (allow_unicode=True)
        material.slug = slugify(slug_text, allow_unicode=True)

        material.save()  # حفظ المادة بالـ Slug الجديد المخصص

        # تنظيف الأسئلة القديمة لحقن التعديلات أو المدخلات الجديدة بأمان دون تكرار
        material.questions.all().delete()

        # قراءة حقول الأسئلة المخفية المرسلة من مفسر نصوص الجافاسكريبت العميل (Client-Side Parser)
        idx = 0
        order = 1
        while f'q{idx}_text' in request.POST:
            q_text = request.POST.get(f'q{idx}_text', '').strip()
            q_exp = request.POST.get(f'q{idx}_explanation', '').strip()
            q_correct = request.POST.get(f'q{idx}_correct', 'a').lower()

            if q_text:
                question = Question.objects.create(
                    material=material,
                    order=order,
                    text=q_text,
                    explanation=q_exp
                )
                choices_to_create = []
                for key in ['a', 'b', 'c', 'd']:
                    choice_text = request.POST.get(f'q{idx}_choice_{key}', '').strip()
                    choices_to_create.append(QuestionChoice(
                        question=question,
                        key=key,
                        text=choice_text,
                        is_correct=(key == q_correct)
                    ))
                QuestionChoice.objects.bulk_create(choices_to_create)
                order += 1
            idx += 1

        # حفظ وإدارة الروابط الديناميكية المرفقة (مثال: لقسم اقرأ واعرف واكسب)
        material.links.all().delete()
        link_types = request.POST.getlist('link_type[]')
        link_urls = request.POST.getlist('link_url[]')
        link_labels = request.POST.getlist('link_label[]')

        links_to_create = []
        for i, url in enumerate(link_urls):
            if url.strip():
                links_to_create.append(MaterialLink(
                    material=material,
                    link_type=link_types[i] if i < len(link_types) else 'article',
                    url=url.strip(),
                    label=link_labels[i].strip() if i < len(link_labels) else '',
                    order=i
                ))
        if links_to_create:
            MaterialLink.objects.bulk_create(links_to_create)

        return redirect('create_material_publish', quiz_slug=material.slug)

    return render(request, 'quiz/panel/create_material.html', {
        'material': material,
        'category': category,
        'category_label': CATEGORY_LABELS.get(category, 'كتاب مقدس'),
        'questions_json': json.dumps(questions_json, ensure_ascii=False),
        'existing_links': existing_links,
        'active': 'create_material_step1' if not quiz_slug else 'manage_materials',
    })

def create_material_publish(request, quiz_slug):
    """صفحة النجاح وتوليد الروابط المباشرة للمسابقة بعد تمام الحفظ"""
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)

    if request.method == 'POST':
        action = request.POST.get('action')
        material.is_active = (action == 'publish')
        material.save()

    # 🟢 تعديل: توليد الرابط ثم فك التشفير عن الحروف العربية ليعود بصيغة واضحة ومقروءة للمستخدم
    raw_url = request.build_absolute_uri(reverse('quiz_view', args=[material.slug]))
    quiz_url = unquote(raw_url)

    return render(request, 'quiz/panel/create_quiz_publish.html', {
        'material': material,
        'quiz_url': quiz_url,
        'active': 'manage_materials',
    })


# دالتين احتياطيتين لمنع أخطاء الروابط القديمة بملف الـ URLs في المشروع
def create_material_preview(request):
    return redirect('create_material_step1')

def parse_preview_ajax(request):
    return JsonResponse({'status': 'deprecated, handled client-side'})