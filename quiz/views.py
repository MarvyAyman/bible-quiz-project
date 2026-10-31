# quiz/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.contenttypes.models import ContentType
from django.db.models import Avg, Count, Sum, Q, Max, F
from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.db.models.functions import TruncDate

from .models import (
    Material, MaterialLink, Question, QuestionChoice, Score,
    QuestionResponse, ActivityComment, ActivityReaction,
    Badge, UserBadge, Category,
)

import json
import re
import os
import uuid
import datetime
import requests
import jwt
from collections import defaultdict
from urllib.parse import unquote


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_CHOICE_KEYS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
CHOICE_KEY_LABELS = {
    'a': 'أ', 'b': 'ب', 'c': 'ج', 'd': 'د',
    'e': 'هـ', 'f': 'و', 'g': 'ز', 'h': 'ح',
}

# خيارات التفاعل المتاحة على بوستات خلاصة النشاط (الدروع المكتسبة)
REACTION_OPTIONS = [
    {'emoji': '🎉', 'label': 'مبارك'},
    {'emoji': '🙏', 'label': 'آمين'},
    {'emoji': '📖', 'label': 'فخر'},
    {'emoji': '✨', 'label': 'نعمة'},
]

# لوحة ألوان أفاتار ثابتة تُختار بناءً على user_id
AVATAR_PALETTE = [
    '#58cc02', '#ff9800', '#1e88e5', '#8e24aa',
    '#e53935', '#00897b', '#6d4c41', '#3949ab',
]


def _avatar_color(user_id):
    return AVATAR_PALETTE[user_id % len(AVATAR_PALETTE)]


def _build_activity_feed(request_user, limit=30):
    """
    يبني قائمة أحدث الدروع المكتسبة (كخلاصة نشاط) مع تفاعلات كل بوست
    مجمّعة بكويري واحد بدلاً من استعلام منفصل لكل بوست (تفادي N+1).
    """
    user_badges = list(
        UserBadge.objects.select_related('user', 'badge').order_by('-earned_at')[:limit]
    )
    if not user_badges:
        return []

    content_type = ContentType.objects.get_for_model(UserBadge)
    object_ids = [ub.id for ub in user_badges]

    reactions_qs = ActivityReaction.objects.filter(
        content_type=content_type, object_id__in=object_ids
    )

    grouped = defaultdict(lambda: defaultdict(int))
    user_reaction_map = {}
    for r in reactions_qs:
        grouped[r.object_id][(r.emoji, r.label)] += 1
        if request_user.is_authenticated and r.user_id == request_user.id:
            user_reaction_map[r.object_id] = r.emoji

    feed = []
    for ub in user_badges:
        reactions = [
            {'emoji': emoji, 'label': label, 'count': count}
            for (emoji, label), count in grouped.get(ub.id, {}).items()
        ]
        display_name = ub.user.get_full_name() or ub.user.username
        feed.append({
            'post_id': ub.id,
            'user_name': display_name,
            'user_initial': display_name[0] if display_name else '؟',
            'avatar_color': _avatar_color(ub.user_id),
            'earned_at': ub.earned_at,
            'badge_name': ub.badge.name,
            'badge_description': ub.badge.description,
            'badge_icon': ub.badge.icon_image_url,
            'reactions': reactions,
            'user_reaction': user_reaction_map.get(ub.id),
        })
    return feed


def decode_url_slug(url_string):
    return unquote(url_string)


# ---------------------------------------------------------------------------
# Public / subscriber views (الواجهة العامة للمشتركين)
# ---------------------------------------------------------------------------

# def index_view(request):
#     """الصفحة الرئيسية للمشتركين مع دعم أزرار الفلترة للأقسام المتاحة (ديناميكي)"""
#     active_categories = list(
#         Category.objects.filter(is_active=True).order_by('order', 'id')
#     )

#     all_active_materials = Material.objects.filter(
#         is_active=True, category__is_active=True
#     )

#     # حساب الأعداد لكل قسم ديناميكياً
#     counts = {'all': all_active_materials.count()}
#     for cat in active_categories:
#         counts[cat.key] = all_active_materials.filter(category=cat).count()

#     category_filter = request.GET.get('category', 'all')

#     if category_filter != 'all':
#         materials = all_active_materials.filter(category__key=category_filter)
#     else:
#         materials = all_active_materials

#     return render(request, 'quiz/index.html', {
#         'materials': materials,
#         'category_filter': category_filter,
#         'counts': counts,
#         'active_categories': active_categories,
#         'activity_feed': _build_activity_feed(request.user),
#         'reaction_options': REACTION_OPTIONS,
#         'SUPABASE_URL': settings.SUPABASE_URL,
#         'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
#     })

def index_view(request):
    """الصفحة الرئيسية للمشتركين — تصنيفات نشطة ديناميكية مع فلترة وعدّادات"""
    active_categories = list(
        Category.objects.filter(is_active=True).order_by('order', 'id')
    )

    all_active_materials = (
        Material.objects
        .filter(is_active=True, category__is_active=True)
        .select_related('category')
    )

    # العدّاد لكل تصنيف (يُستخدم في أزرار الفلترة)
    counts = {'all': all_active_materials.count()}
    for cat in active_categories:
        cat.material_count = all_active_materials.filter(category=cat).count()
        counts[cat.key] = cat.material_count

    # الفلتر المطلوب — لو التصنيف غير موجود أو غير نشط نرجع لـ "الكل"
    category_filter = request.GET.get('category', 'all')
    valid_keys = {cat.key for cat in active_categories}
    if category_filter != 'all' and category_filter not in valid_keys:
        category_filter = 'all'

    if category_filter == 'all':
        materials = all_active_materials
    else:
        materials = all_active_materials.filter(category__key=category_filter)

    materials = materials.order_by('category__order', 'source_name', 'chapter_number')

    return render(request, 'quiz/index.html', {
        'materials': materials,
        'category_filter': category_filter,
        'counts': counts,
        'active_categories': active_categories,
        'activity_feed': _build_activity_feed(request.user),
        'reaction_options': REACTION_OPTIONS,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    })
    
    
    
def quiz_view(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(
        Material.objects.select_related('category'),
        slug=quiz_slug, is_active=True
    )

    questions_data = []
    for q in material.questions.prefetch_related('choices').all():
        choices = [
            {'key': c.key, 'text': c.text}
            for c in q.choices.all() if c.text.strip()
        ]
        questions_data.append({
            'id': q.id,
            'text': q.text,
            'choices': choices,
            'correct': next((c.key for c in q.choices.all() if c.is_correct), 'a'),
            'explanation': q.explanation,
        })

    # 🆕 Only attach links if the category allows them
    if material.category.has_links:
        links = material.links.all()
    else:
        links = MaterialLink.objects.none()

    context = {
        'material': material,
        'links': links,
        'show_links_section': material.category.has_links,   # 🆕 explicit flag for template
        'show_timer': material.category.has_timer,          # 🆕        
        'questions_data': questions_data,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
        
    }
    return render(request, 'quiz/quiz_detail.html', context)


# ---------------------------------------------------------------------------
# Archive.org credentials + upload worker settings
# ---------------------------------------------------------------------------
# ⚠️ ملحوظة أمان: هذه المفاتيح الآن تُمرَّر أيضاً للمتصفح مباشرة (Client-Side)
# لرفع ملفات PDF الكبيرة مباشرة لـ Archive.org بدون المرور على سيرفر Vercel.
# يُفضَّل استخدام حساب Archive.org منفصل مخصص لهذا التطبيق فقط.
IA_ACCESS_KEY = os.environ.get("IA_ACCESS_KEY", "L8yZpkLVeZkbYdXX")
IA_SECRET_KEY = os.environ.get("IA_SECRET_KEY", "XNtm6xCJXtFfOiFA")
IA_ITEM_PREFIX = os.environ.get("IA_ITEM_PREFIX", "ftshuelkotob")
IA_COLLECTION = os.environ.get("IA_COLLECTION", "opensource")
IA_WORKER_URL = os.environ.get("IA_WORKER_URL", "http://localhost:8787")


# ---------------------------------------------------------------------------
# Badge Management (Panel)
# ---------------------------------------------------------------------------

def manage_badges(request):
    badges = Badge.objects.all().select_related('category_filter').order_by('-id')
    counts = {b.id: b.users_earned.count() for b in badges}

    return render(request, 'quiz/panel/manage_badges.html', {
        'badges': badges,
        'counts': counts,
        'active': 'manage_badges',
    })


def badge_create(request):
    if request.method == 'POST':
        condition_type = request.POST.get('condition_type')
        category_key = request.POST.get('category_filter', '').strip()
        cat_obj = Category.objects.filter(key=category_key).first() if category_key else None

        Badge.objects.create(
            name=request.POST.get('name'),
            description=request.POST.get('description'),
            icon_image_url=request.POST.get('icon_image_url', ''),
            condition_type=condition_type,
            threshold_value=int(request.POST.get('threshold_value', 1)),
            category_filter=cat_obj if condition_type != 'streak_days' else None,
            is_active='is_active' in request.POST,
        )
        return redirect('manage_badges')

    context = {
        'condition_types': Badge.CONDITION_CHOICES,
        'category_choices': [('', 'كل التصنيفات')] + [
            (c.key, c.display_name) for c in Category.objects.all().order_by('order')
        ],
        'form_data': {'is_active': True},
        'active': 'manage_badges',
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
        category_key = request.POST.get('category_filter', '').strip()
        cat_obj = Category.objects.filter(key=category_key).first() if category_key else None

        badge_instance.name = request.POST.get('name')
        badge_instance.description = request.POST.get('description')
        badge_instance.icon_image_url = request.POST.get('icon_image_url', '')
        badge_instance.condition_type = condition_type
        badge_instance.threshold_value = int(request.POST.get('threshold_value', 1))

        # streak_days → no category. Otherwise → whatever the admin picked (may be empty)
        badge_instance.category_filter = cat_obj if condition_type != 'streak_days' else None
        badge_instance.is_active = 'is_active' in request.POST

        badge_instance.save()
        return redirect('manage_badges')

    form_data = {
        'name': badge_instance.name,
        'description': badge_instance.description,
        'icon_image_url': badge_instance.icon_image_url,
        'condition_type': badge_instance.condition_type,
        'threshold_value': badge_instance.threshold_value,
        'category_filter': badge_instance.category_filter.key if badge_instance.category_filter else '',
        'is_active': badge_instance.is_active,
    }

    context = {
        'badge': badge_instance,
        'condition_types': Badge.CONDITION_CHOICES,
        'category_choices': [('', 'اختر التصنيف المستهدف...')] + [
            (c.key, c.display_name) for c in Category.objects.all().order_by('order')
        ],
        'form_data': form_data,
        'error': error,
        'active': 'manage_badges',
    }
    return render(request, 'quiz/panel/badge_form.html', context)


@require_POST
def badge_delete(request, badge_id):
    """حذف الدرع نهائياً من النظام ومن سجلات جميع المشتركين الذين حصلوا عليه."""
    badge_instance = get_object_or_404(Badge, id=badge_id)
    badge_instance.delete()
    return redirect('manage_badges')


@require_POST
def badge_toggle(request, badge_id):
    """تغيير حالة الدرع بين التفعيل والتعطيل دون الدخول لصفحة التعديل."""
    badge_instance = get_object_or_404(Badge, id=badge_id)
    badge_instance.is_active = not badge_instance.is_active
    badge_instance.save()
    return redirect('manage_badges')


@csrf_exempt
def upload_badge_image_api(request):
    """
    استقبال الصورة عبر AJAX، رفعها الفوري إلى Archive.org S3 API وإعادة الرابط المباشر.
    """
    if request.method != 'POST' or not request.FILES.get('badge_file'):
        return JsonResponse({'status': 'error', 'message': 'ملف غير صالح أو طلب خاطئ'}, status=400)

    image_file = request.FILES['badge_file']

    unique_id = uuid.uuid4().hex[:10]
    bucket_name = f"quiz_badge_assets_{unique_id}"
    file_ext = os.path.splitext(image_file.name)[1] or '.png'
    target_filename = f"badge_{unique_id}{file_ext}"

    archive_url = f"https://archive.org/download/{bucket_name}/{target_filename}"
    archive_s3_endpoint = f"https://s3.us.archive.org/{bucket_name}/{target_filename}"

    try:
        file_data = image_file.read()
        headers = {
            "Authorization": f"LOW {IA_ACCESS_KEY}:{IA_SECRET_KEY}",
            "Content-Type": image_file.content_type,
            "x-archive-auto-make-bucket": "1",
        }
        response = requests.put(archive_s3_endpoint, data=file_data, headers=headers, timeout=30)

        if response.status_code == 200:
            return JsonResponse({'status': 'success', 'url': archive_url})
        else:
            return JsonResponse({
                'status': 'error',
                'message': f"فشل الرفع لـ Archive.org كود الخطأ: {response.status_code}"
            }, status=500)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f"حدث خطأ أثناء الاتصال: {str(e)}"}, status=500)


# ---------------------------------------------------------------------------
# Submit score + badge engine
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def submit_score(request, quiz_slug):
    """
    استقبال وحفظ نتيجة محاولة المشترك بالكامل، وفحص الدروع المكتسبة تلقائياً.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'عفواً، طلب غير مسموح.'}, status=400)

    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)

    user = request.user
    if not user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'يجب تسجيل الدخول لحفظ النتيجة.'}, status=401)

    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        time_taken_seconds = int(data.get('time_taken_seconds', 0))
        answers = data.get('answers', [])
        if isinstance(answers, str):
            answers = json.loads(answers or '[]')
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'بيانات النتيجة غير صالحة.'}, status=400)

    # تصحيح الإجابات وحساب الدرجة من داخل السيرفر مباشرة (لا نثق بدرجة العميل)
    total_questions = material.questions.count()
    score_value = 0
    responses_to_create = []

    quiz_questions = {q.id: q for q in material.questions.prefetch_related('choices').all()}

    for answer in answers:
        try:
            question_id = int(answer.get('question_id'))
        except (TypeError, ValueError, AttributeError):
            continue

        question = quiz_questions.get(question_id)
        if not question:
            continue

        selected_choice = (answer.get('selected_choice') or '').strip().lower()
        is_correct = bool(selected_choice) and selected_choice == question.first_correct_key

        if is_correct:
            score_value += 1

        responses_to_create.append(QuestionResponse(
            question=question,
            selected_choice=selected_choice,
            is_correct=is_correct,
        ))

    score = Score.objects.create(
        user=user,
        material=material,
        score_value=score_value,
        time_taken_seconds=time_taken_seconds,
    )

    for response in responses_to_create:
        response.score = score
    QuestionResponse.objects.bulk_create(responses_to_create)

    # 🏅 فحص الدروع النشطة (Automated Badge Engine)
    new_earned_badges = []
    active_badges = Badge.objects.filter(is_active=True).select_related('category_filter')
    already_earned_ids = UserBadge.objects.filter(user=user).values_list('badge_id', flat=True)

    for badge in active_badges:
        if badge.id in already_earned_ids:
            continue

        is_eligible = False

        # النوع أ: عدد المسابقات المكتملة
        if badge.condition_type == 'quiz_completion_count':
            qs = Score.objects.filter(user=user)
            if badge.category_filter:
                qs = qs.filter(material__category=badge.category_filter)
            completed_count = qs.values('material').distinct().count()
            if completed_count >= badge.threshold_value:
                is_eligible = True

        # النوع ب: عدد المحاولات ذات الدرجات الكاملة
        elif badge.condition_type == 'perfect_score_count':
            qs = Score.objects.filter(user=user)
            if badge.category_filter:
                qs = qs.filter(material__category=badge.category_filter)

            perfect_count = 0
            for s in qs.select_related('material'):
                total_q = s.material.questions.count()
                if total_q > 0 and s.score_value == total_q:
                    perfect_count += 1

            if perfect_count >= badge.threshold_value:
                is_eligible = True

        # النوع ج: عدد الأيام المتتالية
        elif badge.condition_type == 'streak_days':
            dates = Score.objects.filter(user=user)\
                                 .annotate(date=TruncDate('created_at'))\
                                 .values_list('date', flat=True)\
                                 .distinct()\
                                 .order_by('-date')
            streak = 0
            if dates.exists():
                today = datetime.date.today()
                if dates[0] in [today, today - datetime.timedelta(days=1)]:
                    streak = 1
                    check_date = dates[0]
                    for d in dates[1:]:
                        if check_date - d == datetime.timedelta(days=1):
                            streak += 1
                            check_date = d
                        elif check_date == d:
                            continue
                        else:
                            break
            if streak >= badge.threshold_value:
                is_eligible = True

        if is_eligible:
            UserBadge.objects.create(user=user, badge=badge)
            new_earned_badges.append({
                'id': badge.id,
                'name': badge.name,
                'description': badge.description,
                'icon': badge.icon_image_url or "https://cdn-icons-png.flaticon.com/512/6188/6188595.png",
            })

    redirect_destination = reverse('index')

    return JsonResponse({
        'status': 'success',
        'message': 'تم حفظ النتيجة بنجاح وفحص سجل أوسمتكِ الجارية.',
        'score_id': score.id,
        'score_value': score_value,
        'total_questions': total_questions,
        'redirect_url': redirect_destination,
        'new_badges': new_earned_badges,
    })


# ---------------------------------------------------------------------------
# Activity reactions
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def toggle_activity_reaction(request, user_badge_id):
    """
    إضافة / تبديل / إزالة تفاعل المستخدم الحالي على بوست وسام مكتسب (UserBadge).
    """
    user = request.user
    if not user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'يجب تسجيل الدخول للتفاعل.'}, status=401)

    user_badge = get_object_or_404(UserBadge, id=user_badge_id)
    content_type = ContentType.objects.get_for_model(UserBadge)

    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'بيانات غير صالحة.'}, status=400)

    emoji = (data.get('emoji') or '').strip()
    label = (data.get('label') or '').strip()
    valid_emojis = {opt['emoji'] for opt in REACTION_OPTIONS}
    if emoji not in valid_emojis:
        return JsonResponse({'status': 'error', 'message': 'تفاعل غير مدعوم.'}, status=400)

    existing = ActivityReaction.objects.filter(
        user=user, content_type=content_type, object_id=user_badge.id
    ).first()

    if existing and existing.emoji == emoji:
        existing.delete()
        user_reaction = None
    elif existing:
        existing.emoji = emoji
        existing.label = label
        existing.save(update_fields=['emoji', 'label'])
        user_reaction = emoji
    else:
        ActivityReaction.objects.create(
            user=user, content_type=content_type, object_id=user_badge.id,
            emoji=emoji, label=label,
        )
        user_reaction = emoji

    reactions_qs = ActivityReaction.objects.filter(content_type=content_type, object_id=user_badge.id)
    counts = defaultdict(int)
    labels = {}
    for r in reactions_qs:
        counts[r.emoji] += 1
        labels[r.emoji] = r.label
    reactions = [{'emoji': e, 'label': labels[e], 'count': c} for e, c in counts.items()]

    return JsonResponse({'status': 'success', 'reactions': reactions, 'user_reaction': user_reaction})


# ---------------------------------------------------------------------------
# Materials list (public, by category key)
# ---------------------------------------------------------------------------

def materials_list_client(request, category_key):
    """عرض قائمة المحتوى النشط للجمهور بناءً على مفتاح التصنيف"""
    category = get_object_or_404(Category, key=category_key, is_active=True)
    materials = Material.objects.filter(
        is_active=True, category=category
    ).order_by('source_name', 'chapter_number')

    return render(request, 'quiz/index.html', {
        'materials': materials,
        'category': category.key,
        'category_title': category.display_label,
        'active_categories': list(
            Category.objects.filter(is_active=True).order_by('order', 'id')
        ),
    })


# ---------------------------------------------------------------------------
# Text -> quiz structure parser
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
                'key': key, 'label': CHOICE_KEY_LABELS[key], 'value': '',
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
# Panel Dashboard
# ---------------------------------------------------------------------------

def panel_dashboard(request):
    # ── 1. Global KPI cards ────────────────────────────────────────────────
    total_subscribers = User.objects.filter(is_staff=False).count()
    total_attempts = Score.objects.count()

    avg_time_seconds = Score.objects.aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0
    minutes = int(avg_time_seconds // 60)
    seconds = int(avg_time_seconds % 60)
    avg_time_formatted = f"{minutes:02d}:{seconds:02d}"

    overall_correct = QuestionResponse.objects.filter(is_correct=True).count()
    overall_total = QuestionResponse.objects.count()
    overall_avg_percentage = round((overall_correct / overall_total * 100)) if overall_total else 0

    active_materials_count = Material.objects.filter(is_active=True).count()
    draft_materials_count = Material.objects.filter(is_active=False).count()

    # ── 2. Per-category stats (dynamic from DB) ────────────────────────────
    category_stats = []
    for cat in Category.objects.all().order_by('order', 'id'):
        mat_ids = Material.objects.filter(category=cat).values_list('id', flat=True)
        cat_attempts = Score.objects.filter(material_id__in=mat_ids).count()
        cat_correct = QuestionResponse.objects.filter(
            question__material__category=cat, is_correct=True
        ).count()
        cat_total = QuestionResponse.objects.filter(
            question__material__category=cat
        ).count()
        cat_avg_pct = round((cat_correct / cat_total * 100)) if cat_total else 0
        cat_mat_count = Material.objects.filter(category=cat, is_active=True).count()
        category_stats.append({
            'key': cat.key,
            'label': cat.display_label,
            'attempts': cat_attempts,
            'avg_pct': cat_avg_pct,
            'mat_count': cat_mat_count,
        })

    # ── 3. Materials table (all materials, enriched) ───────────────────────
    materials = list(
        Material.objects.all().select_related('category').order_by('category__order', 'chapter_number')
    )
    for m in materials:
        m.attempts = Score.objects.filter(material=m).count()
        m.num_questions = m.questions.count()

        m_avg_time = Score.objects.filter(material=m).aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0
        m.avg_time_formatted = f"{int(m_avg_time // 60):02d}:{int(m_avg_time % 60):02d}"

        m_correct = QuestionResponse.objects.filter(question__material=m, is_correct=True).count()
        m_total_resp = QuestionResponse.objects.filter(question__material=m).count()
        m.avg_percentage = round((m_correct / m_total_resp * 100)) if m_total_resp else None
        m.avg_score = Score.objects.filter(material=m).aggregate(avg=Avg('score_value'))['avg']
        m.book_name = m.source_name
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
            'question__material__category__name',
        )
        .annotate(wrong_count=Count('id'))
        .order_by('-wrong_count')[:5]
    )
    for hq in hardest_qs:
        total_for_q = QuestionResponse.objects.filter(question_id=hq['question_id']).count()
        hq['wrong_percentage'] = round((hq['wrong_count'] / total_for_q * 100)) if total_for_q else 0
        hq['question_short'] = hq['question__text'][:65] + ('...' if len(hq['question__text']) > 65 else '')

    # ── 5. Top performers ──────────────────────────────────────────────────
    top_performers = (
        QuestionResponse.objects
        .filter(is_correct=True)
        .values('score__user__first_name', 'score__user__username')
        .annotate(correct_total=Count('id'))
        .order_by('-correct_total')[:5]
    )

    # ── 6. Recent activity feed ────────────────────────────────────────────
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

    # ── 7. New subscribers per day — last 7 days ───────────────────────────
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
    daily_map = {row['day']: row['count'] for row in daily_counts_qs}
    ARABIC_DAYS = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
    engagement_trend = []
    for i in range(7):
        d = seven_days_ago + datetime.timedelta(days=i)
        engagement_trend.append({
            'label': ARABIC_DAYS[d.weekday() % 7],
            'count': daily_map.get(d, 0),
        })

    # ── 8. Chart data ──────────────────────────────────────────────────────
    chart_materials = [m for m in materials if m.attempts > 0]

    context = {
        'total_subscribers': total_subscribers,
        'total_attempts': total_attempts,
        'avg_time_formatted': avg_time_formatted,
        'overall_avg_percentage': overall_avg_percentage,
        'active_materials_count': active_materials_count,
        'draft_materials_count': draft_materials_count,
        'category_stats': category_stats,
        'materials': materials,
        'chart_materials': chart_materials,
        'hardest_questions': hardest_qs,
        'top_performers': top_performers,
        'recent_activity': recent_activity,
        'engagement_trend': engagement_trend,
        'active': 'dashboard',
    }
    return render(request, 'quiz/panel/dashboard.html', context)


# ---------------------------------------------------------------------------
# Materials management (Panel)
# ---------------------------------------------------------------------------

def manage_materials(request):
    """عرض جدول إدارة كل المواد مع الفلترة"""
    category_key = request.GET.get('category', 'all')

    qs = Material.objects.all().select_related('category').order_by('-id')
    if category_key and category_key != 'all':
        qs = qs.filter(category__key=category_key)

    categories = (
        Category.objects
        .annotate(material_count=Count('materials'))   # related_name='materials'
        .order_by('order', 'id')
    )

    return render(request, 'quiz/panel/manage_materials.html', {
        'materials': qs,
        'current_category': category_key,
        'counts': {'all': Material.objects.count()},
        'all_categories': categories,
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
# ---------------------------------------------------------------------------
# Field labels/placeholders per category (with sensible defaults)
# ---------------------------------------------------------------------------

CATEGORY_FIELD_META = {
    'bible': {
        'source_label': 'اسم السفر',
        'source_placeholder': 'مثال: سفر التكوين',
        'number_label': 'رقم الأصحاح',
        'number_placeholder': '1',
        'title_label': 'العنوان الفرعي (اختياري)',
        'title_placeholder': 'مثال: آدم وحواء',
    },
    'spiritual': {
        'source_label': 'اسم الكتاب',
        'source_placeholder': 'مثال: حياة التوبة',
        'number_label': 'رقم الفصل',
        'number_placeholder': '1',
        'title_label': 'العنوان الفرعي (اختياري)',
        'title_placeholder': 'مثال: الباب الأول',
    },
    'iqraa': {
        'source_label': 'اسم الكتاب المقرر',
        'source_placeholder': 'مثال: اقرأ واعرف واكسب',
        'number_label': 'رقم الفصل',
        'number_placeholder': '1',
        'title_label': 'العنوان الفرعي (اختياري)',
        'title_placeholder': 'مثال: شخصيات الكتاب المقدس',
    },
}

DEFAULT_FIELD_META = {
    'source_label': 'الموضوع الأساسي',
    'source_placeholder': 'مثال: موضوع الدرس أو المحاضرة',
    'number_label': 'رقم الدرس / الفصل',
    'number_placeholder': '1',
    'title_label': 'العنوان الفرعي (اختياري)',
    'title_placeholder': 'مثال: عنوان إضافي توضيحي',
}

def create_material_step1(request, quiz_slug=None):
    """
    الـ View المدمج والذكي لإنشاء وتعديل المسابقات (صفحة واحدة - Preview Tabs).
    """
    material = None
    questions_json = []
    existing_links = []
    all_categories = Category.objects.all().order_by('order', 'id')

    # 1. Edit mode
    if quiz_slug:
        quiz_slug = unquote(quiz_slug)
        material = get_object_or_404(Material.objects.select_related('category'), slug=quiz_slug)
        category = material.category
        existing_links = material.links.all()

        for q in material.questions.prefetch_related('choices').all():
            choices_dict = {c.key: c.text for c in q.choices.all()}
            correct_choice = next((c.key for c in q.choices.all() if c.is_correct), 'a')
            questions_json.append({
                'text': q.text,
                'explanation': q.explanation,
                'correct': correct_choice,
                'choices': choices_dict,
            })
    else:
        # 2. Create mode — accept dynamic category key from URL
        category_key = request.GET.get('category', '').strip()
        category = (
            Category.objects.filter(key=category_key, is_active=True).first()
            or Category.objects.filter(is_active=True).first()
            or Category.objects.first()
        )

    # 3. Handle submit
    if request.method == 'POST':
        # Resolve the target category FIRST
        posted_cat_key = request.POST.get('category_key')
        if posted_cat_key:
            new_cat = Category.objects.filter(key=posted_cat_key).first()
            if new_cat:
                category = new_cat

        source_name = request.POST.get('source_name', '').strip()
        if category.chapter_number_optional:
            raw_chapter = request.POST.get('chapter_number', '').strip()
            try:
                chapter_number = int(raw_chapter) if raw_chapter else None
            except ValueError:
                chapter_number = None
        else:
            try:
                chapter_number = int(request.POST.get('chapter_number', 1))
            except ValueError:
                chapter_number = 1
        title = request.POST.get('title', '').strip()

        # # Allow changing category from the form
        # posted_cat_key = request.POST.get('category_key')
        # if posted_cat_key:
        #     new_cat = Category.objects.filter(key=posted_cat_key).first()
        #     if new_cat:
        #         category = new_cat

        if not material:
            material = Material(category=category)
            material.is_active = False

        material.category = category
        material.source_name = source_name
        material.chapter_number = chapter_number
        material.title = title

        # Custom slug — only include the chapter part when chapter_number is set
        parts = [source_name]
        if chapter_number is not None:
            parts.append(f"الاصحاح {chapter_number}")
        if title:
            parts.append(title)
        slug_text = " ".join(parts)
        material.slug = slugify(slug_text, allow_unicode=True)
        material.save()

        # Reset questions
        material.questions.all().delete()

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
                    explanation=q_exp,
                )
                choices_to_create = []
                for key in ['a', 'b', 'c', 'd']:
                    choice_text = request.POST.get(f'q{idx}_choice_{key}', '').strip()
                    if choice_text:
                        choices_to_create.append(QuestionChoice(
                            question=question,
                            key=key,
                            text=choice_text,
                            is_correct=(key == q_correct),
                        ))
                QuestionChoice.objects.bulk_create(choices_to_create)
                order += 1
            idx += 1

        # 🆕 Handle links — ONLY if the category allows them
        material.links.all().delete()
        if category.has_links:
            link_types = request.POST.getlist('link_type[]')
            link_urls = request.POST.getlist('link_url[]')
            link_labels = request.POST.getlist('link_label[]')

            links_to_create = []
            for i, url in enumerate(link_urls):
                if url.strip():
                    links_to_create.append(MaterialLink(
                        material=material,
                        link_type=link_types[i] if i < len(link_types) else 'summary_pdf',
                        url=url.strip(),
                        label=link_labels[i].strip() if i < len(link_labels) else '',
                        order=i,
                    ))
            if links_to_create:
                MaterialLink.objects.bulk_create(links_to_create)

        return redirect('create_material_publish', quiz_slug=material.slug)

    
    # اختيار الـ labels/placeholders حسب القسم مع fallback للافتراضي
    field_meta = CATEGORY_FIELD_META.get(
        category.key if category else '',
        DEFAULT_FIELD_META,
    )

    return render(request, 'quiz/panel/create_material.html', {
        'material': material,
        'category': category,
        'category_label': category.display_label if category else '',
        'category_has_links': category.has_links if category else True,
        'category_chapter_optional': category.chapter_number_optional if category else False,   # 🆕
        'category_has_timer': category.has_timer if category else False,                        # 🆕
        'all_categories': all_categories,
        'questions_json': json.dumps(questions_json, ensure_ascii=False),
        'existing_links': existing_links,
        'active': 'create_material_step1' if not quiz_slug else 'manage_materials',
        'IA_WORKER_URL': IA_WORKER_URL,
        'IA_ITEM_PREFIX': IA_ITEM_PREFIX,
        'IA_COLLECTION': IA_COLLECTION,
        'field_meta': field_meta,   # 🆕
    })


def create_material_publish(request, quiz_slug):
    """صفحة النجاح وتوليد الروابط المباشرة للمسابقة بعد تمام الحفظ"""
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)

    if request.method == 'POST':
        action = request.POST.get('action')
        material.is_active = (action == 'publish')
        material.save()

    raw_url = request.build_absolute_uri(reverse('quiz_view', args=[material.slug]))
    quiz_url = unquote(raw_url)

    return render(request, 'quiz/panel/create_quiz_publish.html', {
        'material': material,
        'quiz_url': quiz_url,
        'active': 'manage_materials',
    })


# Backwards-compat stubs
def create_material_preview(request):
    return redirect('create_material_step1')


def parse_preview_ajax(request):
    return JsonResponse({'status': 'deprecated, handled client-side'})


# ---------------------------------------------------------------------------
# 🆕 Category Management (Panel)
# ---------------------------------------------------------------------------

def manage_categories(request):
    """قائمة التصنيفات مع العدّادات وترتيب drag & drop"""
    categories = Category.objects.all().order_by('order', 'id')
    counts = {c.id: Material.objects.filter(category=c).count() for c in categories}

    return render(request, 'quiz/panel/manage_categories.html', {
        'categories': categories,
        'counts': counts,
        'active': 'manage_categories',
    })


def category_create(request):
    if request.method == 'POST':
        key = request.POST.get('key', '').strip().lower()
        name = request.POST.get('name', '').strip()
        label = request.POST.get('label', '').strip()
        icon = request.POST.get('icon', '📁').strip() or '📁'
        is_active = 'is_active' in request.POST
        has_links = 'has_links' in request.POST
        link_mode = request.POST.get('link_mode', 'multiple')
        chapter_number_optional = 'chapter_number_optional' in request.POST   # 🆕
        has_timer = 'has_timer' in request.POST                               # 🆕
        if link_mode not in ('single', 'multiple'):
            link_mode = 'multiple'

        if not key or not name:
            return render(request, 'quiz/panel/category_form.html', {
                'error': 'المعرف والاسم مطلوبان.',
                'form_data': request.POST,
                'active': 'manage_categories',
            })

        if Category.objects.filter(key=key).exists():
            return render(request, 'quiz/panel/category_form.html', {
                'error': f'المعرف "{key}" مستخدم بالفعل.',
                'form_data': request.POST,
                'active': 'manage_categories',
            })

        Category.objects.create(
            key=key,
            name=name,
            label=label,
            icon=icon,
            is_active=is_active,
            has_links=has_links,
            link_mode=link_mode if has_links else 'multiple',
            chapter_number_optional=chapter_number_optional,   # 🆕
            has_timer=has_timer,                               # 🆕
        )
        return redirect('manage_categories')

    return render(request, 'quiz/panel/category_form.html', {
        'form_data': {
            'is_active': True,
            'has_links': True,
            'icon': '📁',
            'link_mode': 'multiple',
            'chapter_number_optional': False,   # 🆕
            'has_timer': False,                 # 🆕
        },
        'active': 'manage_categories',
    })
    
    
def category_edit(request, category_id):
    category = get_object_or_404(Category, id=category_id)

    if request.method == 'POST':
        key = request.POST.get('key', '').strip().lower()
        name = request.POST.get('name', '').strip()
        label = request.POST.get('label', '').strip()
        icon = request.POST.get('icon', '📁').strip() or '📁'
        is_active = 'is_active' in request.POST
        has_links = 'has_links' in request.POST
        link_mode = request.POST.get('link_mode', 'multiple')
        chapter_number_optional = 'chapter_number_optional' in request.POST   # 🆕
        has_timer = 'has_timer' in request.POST                               # 🆕
        if link_mode not in ('single', 'multiple'):
            link_mode = 'multiple'

        if not key or not name:
            return render(request, 'quiz/panel/category_form.html', {
                'category': category,
                'error': 'المعرف والاسم مطلوبان.',
                'form_data': request.POST,
                'active': 'manage_categories',
            })

        if Category.objects.filter(key=key).exclude(id=category.id).exists():
            return render(request, 'quiz/panel/category_form.html', {
                'category': category,
                'error': f'المعرف "{key}" مستخدم بالفعل في تصنيف آخر.',
                'form_data': request.POST,
                'active': 'manage_categories',
            })

        category.key = key
        category.name = name
        category.label = label
        category.icon = icon
        category.is_active = is_active
        category.has_links = has_links
        category.link_mode = link_mode if has_links else 'multiple'
        category.chapter_number_optional = chapter_number_optional   # 🆕
        category.has_timer = has_timer                               # 🆕
        category.save()
        return redirect('manage_categories')

    return render(request, 'quiz/panel/category_form.html', {
        'category': category,
        'form_data': {
            'key': category.key,
            'name': category.name,
            'label': category.label,
            'icon': category.icon,
            'is_active': category.is_active,
            'has_links': category.has_links,
            'link_mode': category.link_mode,
            'chapter_number_optional': category.chapter_number_optional,   # 🆕
            'has_timer': category.has_timer,                               # 🆕
        },
        'active': 'manage_categories',
    })


@require_POST
def category_toggle(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    category.is_active = not category.is_active
    category.save(update_fields=['is_active'])
    return redirect('manage_categories')


@require_POST
def category_delete(request, category_id):
    category = get_object_or_404(Category, id=category_id)

    # Guard: block deletion if materials are still attached
    if Material.objects.filter(category=category).exists():
        return redirect('manage_categories')

    category.delete()
    return redirect('manage_categories')


@csrf_exempt
@require_POST
def category_reorder_api(request):
    """
    Accepts JSON: { "order": [id1, id2, id3, ...] }
    Rewrites the `order` field for all listed categories atomically.
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
        ids = payload.get('order', [])
        ids = [int(i) for i in ids]
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'بيانات غير صالحة'}, status=400)

    with transaction.atomic():
        for index, cat_id in enumerate(ids, start=1):
            Category.objects.filter(id=cat_id).update(order=index)

    return JsonResponse({'status': 'success', 'updated': len(ids)})


# ---------------------------------------------------------------------------
# Subscribers (Panel) — سجل المشتركين
# ---------------------------------------------------------------------------

SUBSCRIBERS_PAGE_SIZE = 30


def _fmt_duration(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _pct(score_value, question_count):
    return round(score_value / question_count * 100) if question_count else 0


def _fmt_dt(dt):
    return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M') if dt else '—'


def manage_subscribers(request):
    """صفحة المشتركين (الهيكل فقط — البيانات تُحمَّل بـ AJAX)"""
    return render(request, 'quiz/panel/subscribers.html', {
        'all_categories': Category.objects.all().order_by('order', 'id'),
        'active': 'subscribers',
    })


def subscribers_api(request):
    """قائمة المشتركين JSON — بحث + فلتر قسم + تقسيم صفحات (Load more)"""
    q = request.GET.get('q', '').strip()
    category_key = request.GET.get('category', 'all')
    try:
        offset = max(int(request.GET.get('offset', 0)), 0)
    except ValueError:
        offset = 0

    # فلتر الدرجات (يُطبَّق على الإحصائيات لو تم اختيار قسم)
    score_filter = None
    if category_key and category_key != 'all':
        score_filter = Q(scores__material__category__key=category_key)

    users = User.objects.filter(is_staff=False)
    if q:
        users = users.filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    users = users.annotate(
        quizzes_count=Count('scores__material', distinct=True, filter=score_filter),
        attempts_count=Count('scores', filter=score_filter),
        last_attempt_at=Max('scores__created_at', filter=score_filter),
    )
    if score_filter is not None:
        users = users.filter(attempts_count__gt=0)   # داخل قسم معيّن: فقط من شارك فيه

    users = users.order_by(F('last_attempt_at').desc(nulls_last=True), 'username')

    total = users.count()
    page_users = list(users[offset:offset + SUBSCRIBERS_PAGE_SIZE])
    ids = [u.id for u in page_users]

    # محاولات مستخدمي الصفحة فقط (كويري واحد) لحساب النسبة المتوسطة وآخر مسابقة
    scores_qs = (
        Score.objects.filter(user_id__in=ids)
        .select_related('material')
        .annotate(qcount=Count('material__questions'))
        .order_by('-created_at')
    )
    if category_key and category_key != 'all':
        scores_qs = scores_qs.filter(material__category__key=category_key)

    per_user = defaultdict(list)
    for s in scores_qs:
        per_user[s.user_id].append(s)

    rows = []
    for u in page_users:
        user_scores = per_user.get(u.id, [])
        last = user_scores[0] if user_scores else None
        avg_pct = round(sum(_pct(s.score_value, s.qcount) for s in user_scores) / len(user_scores)) if user_scores else None
        rows.append({
            'id': u.id,
            'name': u.get_full_name() or u.username,
            'username': u.username,
            'quizzes_count': u.quizzes_count,
            'attempts_count': u.attempts_count,
            'avg_pct': avg_pct,
            'last_quiz': str(last.material) if last else None,
            'last_quiz_pct': _pct(last.score_value, last.qcount) if last else None,
            'last_at': _fmt_dt(u.last_attempt_at),
        })

    return JsonResponse({
        'rows': rows,
        'total': total,
        'next_offset': offset + SUBSCRIBERS_PAGE_SIZE,
        'has_more': offset + SUBSCRIBERS_PAGE_SIZE < total,
    })


def subscriber_detail_api(request, user_id):
    """سجل مشترك واحد: لكل مسابقة (أول مرة / آخر مرة / أفضل نتيجة / عدد المحاولات)"""
    user = get_object_or_404(User, id=user_id, is_staff=False)

    scores = (
        Score.objects.filter(user=user)
        .select_related('material', 'material__category')
        .annotate(qcount=Count('material__questions'))
        .order_by('created_at')
    )

    groups = {}
    for s in scores:
        title_parts = [s.material.source_name, str(s.material.chapter_number)]
        title = f"{s.material.source_name} — {s.material.chapter_number}"
        if s.material.title:
            title += f" ({s.material.title})"

        g = groups.setdefault(s.material_id, {
            'title': title,
            'category': s.material.category.display_label if s.material.category_id else '—',
            'category_icon': s.material.category.icon if s.material.category_id else '📁',
            'questions': s.qcount,
            'attempts': 0,
            'first': s,
            'last': s,
            'best': s,
        })
        g['attempts'] += 1
        g['last'] = s
        if (s.score_value, -s.time_taken_seconds) > (g['best'].score_value, -g['best'].time_taken_seconds):
            g['best'] = s

    def attempt_dict(s, q):
        return {
            'score': s.score_value,
            'total': q,
            'pct': _pct(s.score_value, q),
            'time': _fmt_duration(s.time_taken_seconds),
            'date': _fmt_dt(s.created_at),
        }

    quizzes = []
    for g in sorted(groups.values(), key=lambda x: x['last'].created_at, reverse=True):
        first = attempt_dict(g['first'], g['questions'])
        last = attempt_dict(g['last'], g['questions'])
        quizzes.append({
            'title': g['title'],
            'category': g['category'],
            'category_icon': g['category_icon'],
            'attempts': g['attempts'],
            'first': first,
            'last': last,
            'best': attempt_dict(g['best'], g['questions']),
            'improvement': last['pct'] - first['pct'] if g['attempts'] > 1 else None,
        })

    all_pcts = [q['best']['pct'] for q in quizzes]
    return JsonResponse({
        'name': user.get_full_name() or user.username,
        'username': user.username,
        'joined': _fmt_dt(user.date_joined),
        'quizzes_count': len(quizzes),
        'attempts_count': sum(q['attempts'] for q in quizzes),
        'avg_best_pct': round(sum(all_pcts) / len(all_pcts)) if all_pcts else None,
        'quizzes': quizzes,
    })