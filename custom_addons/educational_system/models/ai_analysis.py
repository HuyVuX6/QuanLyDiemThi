# -*- coding: utf-8 -*-
from odoo import models, fields, api
import json
import logging
import requests

_logger = logging.getLogger(__name__)

class AIAnalysis(models.Model):
    _name = 'ai.analysis'
    _description = 'Phân Tích AI'
    _rec_name = 'name'

    _sql_constraints = [
        ('unique_session', 'UNIQUE(session_id)', 'Mỗi phiên thi chỉ có 1 bản phân tích!'),
    ]

    name = fields.Char(string='Tiêu Đề', compute='_compute_name', store=True)
    session_id = fields.Many2one('exam.session', string='Phiên Thi', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Học Sinh', required=True, ondelete='cascade')
    status = fields.Selection([
        ('pending', 'Chờ Xử Lý'),
        ('processing', 'Đang Phân Tích'),
        ('completed', 'Hoàn Thành'),
        ('failed', 'Lỗi')
    ], default='pending', string='Trạng Thái')

    ai_model_version = fields.Char(string='Mô Hình AI', default='claude-3-sonnet-20240229')
    strengths = fields.Text(string='Điểm Mạnh')
    weaknesses = fields.Text(string='Điểm Yếu')
    feedback = fields.Text(string='Nhận Xét Sư Phạm')
    suggestions = fields.Text(string='Gợi Ý Luyện Tập')
    error_message = fields.Text(string='Thông Báo Lỗi')
    analysis_date = fields.Datetime(string='Thời Gian Phân Tích')

    @api.depends('student_id.name', 'session_id.name')
    def _compute_name(self):
        for record in self:
            record.name = f"AI: {record.student_id.name or ''} ({record.session_id.exam_id.name or ''})"

    def action_analyze_with_claude(self):
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai.claude_api_key')
        
        if not api_key:
            self.write({
                'status': 'failed',
                'error_message': 'Chưa nhập Claude API Key trong System Parameters (khóa: ai.claude_api_key)!'
            })
            return

        self.write({'status': 'processing'})

        session = self.session_id
        topic_summary = {}
        for ans in session.answer_ids:
            top = ans.question_id.topic or 'Khác'
            if top not in topic_summary:
                topic_summary[top] = {'correct': 0, 'total': 0}
            topic_summary[top]['total'] += 1
            if ans.is_correct:
                topic_summary[top]['correct'] += 1

        prompt = f"""
Bạn là giáo viên dạy Toán lớp 3. Hãy phân tích bài thi của học sinh:
- Tên: {self.student_id.name}
- Đề thi: {session.exam_id.name}
- Điểm: {session.total_score}/{session.total_possible} ({session.percentage:.1f}%)
- Chi tiết câu đúng/sai theo dạng toán: {json.dumps(topic_summary, ensure_ascii=False)}

Chỉ trả về định dạng JSON thuần túy (không kèm markdown):
{{
    "strengths": "Điểm mạnh",
    "weaknesses": "Điểm yếu",
    "feedback": "Nhận xét sư phạm ngắn gọn (2-3 câu)",
    "suggestions": "Gợi ý lộ trình ôn tập"
}}
"""
        try:
            headers = {
                'Content-Type': 'application/json',
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01'
            }
            payload = {
                'model': self.ai_model_version,
                'max_tokens': 1000,
                'messages': [{'role': 'user', 'content': prompt}]
            }
            res = requests.post('https://api.anthropic.com/v1/messages', json=payload, headers=headers, timeout=20)
            
            if res.status_code != 200:
                raise Exception(f"Lỗi Anthropic ({res.status_code}): {res.text}")

            raw = res.json()['content'][0]['text'].strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            elif raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]

            data = json.loads(raw.strip())
            self.write({
                'strengths': data.get('strengths', ''),
                'weaknesses': data.get('weaknesses', ''),
                'feedback': data.get('feedback', ''),
                'suggestions': data.get('suggestions', ''),
                'status': 'completed',
                'analysis_date': fields.Datetime.now(),
                'error_message': False,
            })
        except Exception as e:
            _logger.error(f"AI Failure: {str(e)}")
            self.write({
                'status': 'failed',
                'error_message': str(e),
            })