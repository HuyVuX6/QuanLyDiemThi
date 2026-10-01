# -*- coding: utf-8 -*-
{
    'name': 'Educational System - AI Grade 3 Math',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': 'Quản lý lớp học Toán 3 và phân tích bài làm bằng Claude AI',
    'author': 'Vũ Ngọc Huy',
    'depends': ['base', 'web'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/security_rules.xml',
        'data/ir_cron_data.xml',
        'views/school_views.xml',
        'views/exam_views.xml',
        'views/ai_analysis_views.xml',
        'views/menuchinh_views.xml',
        'data/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'educational_system/static/src/js/exam_countdown_timer.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}