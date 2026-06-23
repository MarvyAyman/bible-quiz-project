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
import jwt
from urllib.parse import unquote
from django.views.decorators.csrf import csrf_exempt

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
    materials = Material.objects.filter(is_active=True).order_by('category', 'chapter_number')
    context = {
        'materials': materials,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
    return render(request, 'quiz/index.html', context)


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


@csrf_exempt
@require_POST
def submit_score(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug, is_active=True)
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({'status': 'error', 'message': 'غير مصرح به'}, status=401)

    token = auth_header.split(' ')[1]
    try:
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
        supabase_uid = payload['sub']
        email = payload.get('email', f"{supabase_uid}@supabase.local")
        user_metadata = payload.get('user_metadata', {})
        full_name = user_metadata.get('full_name', email.split('@')[0])
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'رمز غير صالح'}, status=401)

    user, _created = User.objects.get_or_create(
        username=supabase_uid, defaults={'email': email, 'first_name': full_name}
    )

    login(request, user)

    try:
        data = json.loads(request.body)
        time_taken_seconds = int(data.get('time_taken_seconds', 0))
        answers = data.get('answers', [])
        if not isinstance(answers, list):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'بيانات غير صالحة'}, status=400)

    questions = {q.id: q for q in material.questions.prefetch_related('choices').all()}
    score_value = 0
    response_rows = []

    for answer in answers:
        try:
            question_id = int(answer.get('question_id'))
            selected_choice = answer.get('selected_choice')
        except (TypeError, ValueError, AttributeError):
            continue
        question = questions.get(question_id)
        if not question or selected_choice not in ALL_CHOICE_KEYS:
            continue
        is_correct = question.choices.filter(key=selected_choice, is_correct=True).exists()
        if is_correct:
            score_value += 1
        response_rows.append((question, selected_choice, is_correct))

    score = Score.objects.create(
        user=user, material=material, score_value=score_value, time_taken_seconds=time_taken_seconds,
    )
    QuestionResponse.objects.bulk_create([
        QuestionResponse(score=score, question=q, selected_choice=c, is_correct=ic)
        for q, c, ic in response_rows
    ])

    return JsonResponse({
        'status': 'success',
        'score_value': score_value,
        'total_questions': material.questions.count(),
        'redirect_url': reverse('leaderboard_view', args=[material.slug]),
    })


def leaderboard_view(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    material = get_object_or_404(Material, slug=quiz_slug)

    current_user_uid = request.GET.get('uid', '')  

    seen_users = set()
    all_ranked = []

    for score in Score.objects.filter(material=material).select_related('user').order_by('-score_value', 'time_taken_seconds'):
        if score.user_id not in seen_users:
            seen_users.add(score.user_id)
            minutes = score.time_taken_seconds // 60
            seconds = score.time_taken_seconds % 60
            score.formatted_time = f"{minutes:02d}:{seconds:02d}"
            all_ranked.append(score)

    top_scores = all_ranked[:10]

    current_user_rank = None
    current_user_score = None
    current_user_time = None
    current_user_name = None

    if current_user_uid:
        for idx, score in enumerate(all_ranked):
            if score.user.username == current_user_uid:
                rank = idx + 1
                if rank > 10:
                    current_user_rank = rank
                    current_user_score = score.score_value
                    current_user_time = score.formatted_time
                    current_user_name = score.user.first_name if score.user.first_name else score.user.username
                break

    return render(request, 'quiz/leaderboard.html', {
        'material': material,
        'leaderboard': top_scores,
        'current_user_uid': current_user_uid,
        'current_user_rank': current_user_rank,
        'current_user_score': current_user_score,
        'current_user_time': current_user_time,
        'current_user_name': current_user_name,
    })


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

def panel_dashboard(request):
    total_subscribers = User.objects.filter(is_staff=False).count()
    total_attempts = Score.objects.count()
    avg_time_seconds = Score.objects.aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0

    minutes = int(avg_time_seconds // 60)
    seconds = int(avg_time_seconds % 60)
    avg_time_formatted = f"{minutes:02d}:{seconds:02d}"

    materials = Material.objects.all()
    overall_correct = QuestionResponse.objects.filter(is_correct=True).count()
    overall_total = QuestionResponse.objects.count()
    overall_avg_percentage = round((overall_correct / overall_total * 100)) if overall_total > 0 else 0

    for m in materials:
        m.attempts = Score.objects.filter(material=m).count()
        m.num_questions = m.questions.count()

        m_avg_time = Score.objects.filter(material=m).aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0
        m_mins = int(m_avg_time // 60)
        m_secs = int(m_avg_time % 60)
        m.avg_time_formatted = f"{m_mins:02d}:{m_secs:02d}"

        m_correct = QuestionResponse.objects.filter(question__material=m, is_correct=True).count()
        m_total_resp = QuestionResponse.objects.filter(question__material=m).count()
        m.avg_percentage = round((m_correct / m_total_resp * 100)) if m_total_resp > 0 else None
        m.avg_score = Score.objects.filter(material=m).aggregate(avg=Avg('score_value'))['avg']

    hardest_qs = QuestionResponse.objects.filter(is_correct=False) \
        .values('question_id', 'question__text', 'question__material__source_name', 'question__material__chapter_number') \
        .annotate(wrong_count=Count('id')) \
        .order_by('-wrong_count')[:5]

    for hq in hardest_qs:
        total_answers_for_q = QuestionResponse.objects.filter(question_id=hq['question_id']).count()
        hq['wrong_percentage'] = round((hq['wrong_count'] / total_answers_for_q * 100)) if total_answers_for_q > 0 else 0
        hq['question_short'] = hq['question__text'][:60] + ('...' if len(hq['question__text']) > 60 else '')

    context = {
        'total_subscribers': total_subscribers,
        'total_attempts': total_attempts,
        'avg_time_formatted': avg_time_formatted,
        'overall_avg_percentage': overall_avg_percentage,
        'materials': materials,
        'hardest_questions': hardest_qs,
        'active': 'dashboard',
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