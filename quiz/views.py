from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.db.models import Avg, Count
from django.conf import settings
from .models import Quiz, Question, QuestionChoice, Score, QuestionResponse
import json
import re
import jwt
from urllib.parse import unquote
from django.views.decorators.csrf import csrf_exempt


def decode_url_slug(url_string):
    return unquote(url_string)

# All valid choice keys in order
ALL_CHOICE_KEYS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
CHOICE_KEY_LABELS = {'a': 'أ', 'b': 'ب', 'c': 'ج', 'd': 'د', 'e': 'هـ', 'f': 'و', 'g': 'ز', 'h': 'ح'}

# ---------------------------------------------------------------------------
# Public / subscriber views
# ---------------------------------------------------------------------------

def index_view(request):
    quizzes = Quiz.objects.filter(is_active=True).order_by('book_name', 'chapter_number')
    context = {
        'quizzes': quizzes,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
    return render(request, 'quiz/index.html', context)


def quiz_view(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    quiz = get_object_or_404(Quiz, slug=quiz_slug, is_active=True)
    questions_data = []
    for q in quiz.questions.prefetch_related('choices').all():
        choices = [
            {'key': c.key, 'text': c.text}
            for c in q.choices.all()
        ]
        correct_choice = q.first_correct_key
        questions_data.append({
            'id': q.id,
            'text': q.text,
            'choices': choices,
            'correct': correct_choice,
            'explanation': q.explanation,
        })

    context = {
        'quiz': quiz,
        'questions_data': questions_data,
        'SUPABASE_URL': settings.SUPABASE_URL,
        'SUPABASE_ANON_KEY': settings.SUPABASE_ANON_KEY,
    }
    return render(request, 'quiz/quiz_detail.html', context)


@csrf_exempt
@require_POST
def submit_score(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    quiz = get_object_or_404(Quiz, slug=quiz_slug, is_active=True)
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return JsonResponse({'status': 'error', 'message': 'غير مصرح به'}, status=401)

    token = auth_header.split(' ')[1]

    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        supabase_uid = payload['sub']
        email = payload.get('email', f"{supabase_uid}@supabase.local")
        user_metadata = payload.get('user_metadata', {})
        full_name = user_metadata.get('full_name', email.split('@')[0])
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'رمز غير صالح'}, status=401)

    user, _created = User.objects.get_or_create(
        username=supabase_uid,
        defaults={'email': email, 'first_name': full_name}
    )

    try:
        data = json.loads(request.body)
        time_taken_seconds = int(data.get('time_taken_seconds', 0))
        answers = data.get('answers', [])
        if not isinstance(answers, list):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'status': 'error', 'message': 'بيانات غير صالحة'}, status=400)

    questions = {q.id: q for q in quiz.questions.prefetch_related('choices').all()}
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
        user=user,
        quiz=quiz,
        score_value=score_value,
        time_taken_seconds=time_taken_seconds,
    )

    QuestionResponse.objects.bulk_create([
        QuestionResponse(score=score, question=q, selected_choice=c, is_correct=ic)
        for q, c, ic in response_rows
    ])

    return JsonResponse({
        'status': 'success',
        'score_value': score_value,
        'total_questions': quiz.question_count,
        'redirect_url': reverse('leaderboard_view', args=[quiz.slug]),
    })


def leaderboard_view(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    quiz = get_object_or_404(Quiz, slug=quiz_slug)
    top_scores = Score.objects.filter(quiz=quiz).order_by('-score_value', 'time_taken_seconds')[:10]

    for score in top_scores:
        minutes = score.time_taken_seconds // 60
        seconds = score.time_taken_seconds % 60
        score.formatted_time = f"{minutes:02d}:{seconds:02d}"

    return render(request, 'quiz/leaderboard.html', {'quiz': quiz, 'leaderboard': top_scores})

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
    # Ensure at least a and b exist even if empty
    existing_keys = [c['key'] for c in question['choices']]
    for key in ['a', 'b']:
        if key not in existing_keys:
            question['choices'].insert(['a', 'b'].index(key), {
                'key': key, 'label': CHOICE_KEY_LABELS[key], 'value': ''
            })
    return question


def parse_quiz_text(raw_text):
    questions = []
    current = None
    collecting = None

    for raw_line in raw_text.splitlines():
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
# Panel (staff-only) views
# ---------------------------------------------------------------------------

def panel_dashboard(request):
    total_subscribers = User.objects.filter(is_staff=False).count()
    total_attempts = Score.objects.count()
    avg_time_seconds = Score.objects.aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0

    minutes = int(avg_time_seconds // 60)
    seconds = int(avg_time_seconds % 60)
    avg_time_formatted = f"{minutes:02d}:{seconds:02d}"

    quizzes = Quiz.objects.all()
    overall_correct = QuestionResponse.objects.filter(is_correct=True).count()
    overall_total = QuestionResponse.objects.count()
    overall_avg_percentage = round((overall_correct / overall_total * 100)) if overall_total > 0 else 0

    for q in quizzes:
        q.attempts = Score.objects.filter(quiz=q).count()
        q.num_questions = q.questions.count()

        q_avg_time = Score.objects.filter(quiz=q).aggregate(avg=Avg('time_taken_seconds'))['avg'] or 0
        q_mins = int(q_avg_time // 60)
        q_secs = int(q_avg_time % 60)
        q.avg_time_formatted = f"{q_mins:02d}:{q_secs:02d}"

        q_correct = QuestionResponse.objects.filter(question__quiz=q, is_correct=True).count()
        q_total_resp = QuestionResponse.objects.filter(question__quiz=q).count()
        q.avg_percentage = round((q_correct / q_total_resp * 100)) if q_total_resp > 0 else None
        q.avg_score = Score.objects.filter(quiz=q).aggregate(avg=Avg('score_value'))['avg']

    hardest_qs = QuestionResponse.objects.filter(is_correct=False) \
        .values('question_id', 'question__text', 'question__quiz__book_name', 'question__quiz__chapter_number') \
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
        'quizzes': quizzes,
        'hardest_questions': hardest_qs,
        'active_tab': 'dashboard',
    }
    return render(request, 'quiz/panel/dashboard.html', context)


def manage_quizzes(request):
    quizzes = Quiz.objects.all().order_by('-created_at')
    return render(request, 'quiz/panel/manage_quizzes.html', {
        'quizzes': quizzes,
        'active_tab': 'manage_quizzes'
    })


def delete_quiz(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    quiz = get_object_or_404(Quiz, slug=quiz_slug)
    quiz.delete()
    return redirect('manage_quizzes')


def create_quiz_step1(request):
    error = None
    form_data = request.session.get('quiz_step1_data', {})

    if request.method == 'POST':
        book_name = request.POST.get('book_name', '').strip()
        chapter_number = request.POST.get('chapter_number', '').strip()
        title = request.POST.get('title', '').strip()
        raw_text = request.POST.get('raw_text', '').strip()
        uploaded_file = request.FILES.get('quiz_file')

        if uploaded_file:
            try:
                raw_text = extract_text_from_file(uploaded_file)
            except Exception as e:
                error = str(e)

        if not raw_text:
            error = "من فضلك الصق نص الأسئلة أو ارفع ملف يحتوي عليها."

        form_data = {
            'book_name': book_name,
            'chapter_number': chapter_number,
            'title': title,
            'raw_text': raw_text
        }
        request.session['quiz_step1_data'] = form_data

        if not error:
            parsed_questions = parse_quiz_text(raw_text)
            if not parsed_questions:
                error = "لم نتمكن من العثور على أي أسئلة بالتنسيق المطلوب، يرجى مراجعة طريقة الكتابة."
            else:
                request.session['parsed_questions'] = parsed_questions
                request.session['quiz_meta'] = {
                    'book_name': book_name,
                    'chapter_number': chapter_number,
                    'title': title
                }
                return redirect('create_quiz_preview')

    return render(request, 'quiz/panel/create_quiz_step1.html', {
        'error': error,
        'form_data': form_data,
        'active_tab': 'new_quiz'
    })


def _save_questions_from_post(request, quiz):
    """Helper: reads q{i}_* fields from POST and saves Question + QuestionChoice rows."""
    try:
        total_qs = int(request.POST.get('total_questions', 0))
    except ValueError:
        total_qs = 0

    order = 1
    for i in range(total_qs):
        text = request.POST.get(f'q{i}_text', '').strip()
        if not text:
            continue

        # How many choices were submitted for this question
        try:
            num_choices = int(request.POST.get(f'q{i}_num_choices', 4))
        except ValueError:
            num_choices = 4

        num_choices = max(2, min(8, num_choices))
        correct_key = request.POST.get(f'q{i}_correct', 'a')

        question = Question.objects.create(
            quiz=quiz,
            order=order,
            text=text,
            explanation=request.POST.get(f'q{i}_explanation', '').strip(),
        )

        choices_to_create = []
        for idx, key in enumerate(ALL_CHOICE_KEYS[:num_choices]):
            choice_text = request.POST.get(f'q{i}_choice_{key}', '').strip()
            if not choice_text and key not in ('a', 'b'):
                continue  # skip empty optional choices
            choices_to_create.append(QuestionChoice(
                question=question,
                key=key,
                text=choice_text,
                is_correct=(key == correct_key),
                order=idx,
            ))

        QuestionChoice.objects.bulk_create(choices_to_create)
        order += 1


def create_quiz_preview(request):
    parsed_questions = request.session.get('parsed_questions', [])
    quiz_meta = request.session.get('quiz_meta', {})

    if not parsed_questions or not quiz_meta:
        return redirect('create_quiz_step1')

    if request.method == 'POST':
        book_name = request.POST.get('book_name', '').strip()
        chapter_number = int(request.POST.get('chapter_number'))
        title = request.POST.get('title', '').strip()

        quiz = Quiz.objects.create(
            book_name=book_name,
            chapter_number=chapter_number,
            title=title
        )
        _save_questions_from_post(request, quiz)

        request.session.pop('parsed_questions', None)
        request.session.pop('quiz_meta', None)
        request.session.pop('quiz_step1_data', None)

        from urllib.parse import unquote as _unquote
        return redirect('create_quiz_publish', quiz_slug=_unquote(quiz.slug))

    return render(request, 'quiz/panel/create_quiz_preview.html', {
        'questions': parsed_questions,
        'quiz_meta': quiz_meta,
        'active_tab': 'new_quiz',
    })


def create_quiz_publish(request, quiz_slug):
    from urllib.parse import unquote as _unquote
    decoded_slug = _unquote(quiz_slug)
    try:
        quiz = Quiz.objects.get(slug=decoded_slug)
    except Quiz.DoesNotExist:
        quiz = get_object_or_404(Quiz, slug=quiz_slug)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish':
            quiz.is_active = True
            quiz.save()
        elif action == 'unpublish':
            quiz.is_active = False
            quiz.save()

    raw_url = request.build_absolute_uri(reverse('quiz_view', args=[quiz.slug]))
    quiz_url = decode_url_slug(raw_url)

    return render(request, 'quiz/panel/create_quiz_publish.html', {
        'quiz': quiz,
        'quiz_url': quiz_url,
        'active_tab': 'new_quiz',
    })


def edit_existing_quiz(request, quiz_slug):
    quiz_slug = unquote(quiz_slug)
    quiz = get_object_or_404(Quiz, slug=quiz_slug)

    if request.method == 'POST':
        quiz.book_name = request.POST.get('book_name', '').strip()
        quiz.chapter_number = int(request.POST.get('chapter_number'))
        quiz.title = request.POST.get('title', '').strip()
        quiz.slug = ""
        quiz.save()

        quiz.questions.all().delete()  # cascades to QuestionChoice
        _save_questions_from_post(request, quiz)
        return redirect('manage_quizzes')

    # Build questions list for template
    questions_list = []
    for q in quiz.questions.prefetch_related('choices').all():
        choices = [
            {'key': c.key, 'label': CHOICE_KEY_LABELS.get(c.key, c.key), 'value': c.text, 'is_correct': c.is_correct}
            for c in q.choices.all()
        ]
        correct_key = next((c['key'] for c in choices if c['is_correct']), 'a')
        questions_list.append({
            'text': q.text,
            'correct': correct_key,
            'explanation': q.explanation,
            'choices': choices,
        })

    return render(request, 'quiz/panel/create_quiz_preview.html', {
        'questions': questions_list,
        'quiz_meta': {
            'book_name': quiz.book_name,
            'chapter_number': quiz.chapter_number,
            'title': quiz.title
        },
        'is_editing_existing': True,
        'quiz': quiz,
        'active_tab': 'manage_quizzes'
    })