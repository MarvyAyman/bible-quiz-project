from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.index_view, name='index'),

    # ── Public quiz pages ────────────────────────────────────────────────────
    re_path(r'^quiz/(?P<quiz_slug>[^/]+)/$',        views.quiz_view,    name='quiz_view'),
    re_path(r'^quiz/(?P<quiz_slug>[^/]+)/submit/$', views.submit_score, name='submit_score'),

    # ── Activity feed ───────────────────────────────────────────────────────
    path('activity/react/<int:user_badge_id>/', views.toggle_activity_reaction, name='toggle_activity_reaction'),

    # ── Public category lists — now driven by Category.key ──────────────────
    re_path(r'^category/(?P<category_key>[^/]+)/$', views.materials_list_client, name='category_list'),

    # Backward-compat aliases (optional — remove if you update all links)
    path('bible/',     views.materials_list_client, {'category_key': 'bible'},     name='bible_list'),
    path('spiritual/', views.materials_list_client, {'category_key': 'spiritual'}, name='spiritual_list'),
    path('iqraa/',     views.materials_list_client, {'category_key': 'iqraa'},     name='iqraa_list'),

    # ── Control Panel ─────────────────────────────────────────────────────────
    path('panel/',            views.manage_subscribers, name='manage_subscribers'),
    path('panel/dashboard/',  views.panel_dashboard,    name='panel_dashboard'),
    path('panel/materials/',  views.manage_materials,   name='manage_materials'),
    

    path('panel/materials/new/',     views.create_material_step1,   name='create_material_step1'),
    path('panel/materials/preview/', views.create_material_preview, name='create_material_preview'),

    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/edit/$',    views.create_material_step1,   name='edit_material'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/publish/$', views.create_material_publish, name='create_material_publish'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/delete/$',  views.delete_material,         name='delete_material'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/toggle/$',  views.material_publish_toggle, name='material_publish_toggle'),

    # ── Badge Management ────────────────────────────────────────────────────
    path('panel/badges/',                       views.manage_badges, name='manage_badges'),
    path('panel/badges/new/',                   views.badge_create,  name='badge_create'),
    path('panel/badges/<int:badge_id>/edit/',   views.badge_edit,    name='badge_edit'),
    path('panel/badges/<int:badge_id>/toggle/', views.badge_toggle,  name='badge_toggle'),
    path('panel/badges/<int:badge_id>/delete/', views.badge_delete,  name='badge_delete'),
    path('panel/badges/upload-api/',            views.upload_badge_image_api, name='upload_badge_image_api'),

    # ── Category Management (NEW) ───────────────────────────────────────────
    path('panel/categories/',                        views.manage_categories,       name='manage_categories'),
    path('panel/categories/new/',                    views.category_create,         name='category_create'),
    path('panel/categories/<int:category_id>/edit/', views.category_edit,           name='category_edit'),
    path('panel/categories/<int:category_id>/toggle/', views.category_toggle,       name='category_toggle'),
    path('panel/categories/<int:category_id>/delete/', views.category_delete,       name='category_delete'),
    path('panel/categories/reorder/',                views.category_reorder_api,    name='category_reorder_api'),
    path('panel/subscribers/',                    views.manage_subscribers,    name='manage_subscribers'),
path('panel/subscribers/api/',                views.subscribers_api,       name='subscribers_api'),
path('panel/subscribers/<int:user_id>/api/',  views.subscriber_detail_api, name='subscriber_detail_api'),

]