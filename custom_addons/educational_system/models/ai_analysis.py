# -*- coding: utf-8 -*-
from odoo import models, fields, api
import json
import logging
import os
import requests

_logger = logging.getLogger(__name__)

class AIAnalysis(models.Model):
    _name = 'ai.analysis'
    _description = 'Phân Tích Sư Phạm AI'
    _rec_name = 'name'

    _order = 'analysis_date desc, id desc'

    _sql_constraints = [
        ('unique_session', 'UNIQUE(session_id)', 'Mỗi phiên thi chỉ có 1 bản phân tích!'),
    ]

    name = fields.Char(string='Tiêu Đề', compute='_compute_name', store=True)
    session_id = fields.Many2one('exam.session', string='Phiên Thi', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Học Sinh', required=True, ondelete='cascade')
    student_code = fields.Char(string='Mã HS', related='student_id.code', store=True, readonly=True)
    class_id = fields.Many2one('school.class', string='Lớp Học', related='session_id.class_id', store=True, readonly=True)
    batch_id = fields.Many2one('exam.batch', string='Phiên Thi / Đợt Kiểm Tra', related='session_id.batch_id', store=True, readonly=True)
    exam_id = fields.Many2one('exam.exam', string='Đề Thi', related='session_id.exam_id', store=True, readonly=True)
    exam_code = fields.Char(string='Mã Đề', related='session_id.exam_code', store=True, readonly=True)
    total_score = fields.Float(string='Điểm Số Bài Thi', related='session_id.total_score', store=True, readonly=True)
    correct_ratio = fields.Char(string='Số Câu Đúng', related='session_id.correct_ratio', store=True, readonly=True)
    passed = fields.Boolean(string='Kết Quả Đạt', related='session_id.passed', store=True, readonly=True)
    result_display = fields.Char(string='Kết Quả', compute='_compute_result_display', store=True)
    status = fields.Selection([
        ('pending', 'Chờ Xử Lý'),
        ('processing', 'Đang Phân Tích'),
        ('completed', 'Hoàn Thành'),
        ('failed', 'Lỗi')
    ], default='pending', string='Trạng Thái', required=True)

    ai_model_version = fields.Char(string='Mô Hình AI', default='gemini-2.5-flash')
    ai_model_display = fields.Char(string='Công Nghệ AI', compute='_compute_ai_model_display', store=True)
    strengths = fields.Text(string='Điểm Mạnh (Dạng toán nắm vững)')
    weaknesses = fields.Text(string='Điểm Yếu (Dạng toán hay sai)')
    feedback = fields.Text(string='Nhận Xét Sư Phạm Chi Tiết')
    suggestions = fields.Text(string='Gợi Ý / Lộ Trình Cải Thiện')
    error_message = fields.Text(string='Thông Báo Lỗi')
    analysis_date = fields.Datetime(string='Thời Gian Phân Tích')

    @api.depends('passed', 'status', 'total_score')
    def _compute_result_display(self):
        for record in self:
            if record.passed or (record.total_score is not None and record.total_score >= 5.0):
                record.result_display = 'ĐẠT'
            else:
                record.result_display = 'CHƯA ĐẠT'

    @api.depends('ai_model_version')
    def _compute_ai_model_display(self):
        for record in self:
            v = (record.ai_model_version or '').lower()
            if 'gemini' in v:
                record.ai_model_display = 'Gemini AI'
            elif 'claude' in v:
                record.ai_model_display = 'Claude AI'
            else:
                record.ai_model_display = record.ai_model_version or 'AI'

    @api.depends('student_id.name', 'session_id.name')
    def _compute_name(self):
        for record in self:
            s_name = record.student_id.name or 'Học sinh'
            e_name = record.session_id.exam_id.name or 'Bài thi'
            record.name = f"AI: {s_name} - {e_name}"

    def action_retry_analysis(self):
        """Đặt lại trạng thái về pending để tiến hành phân tích lại"""
        for record in self:
            record.write({
                'status': 'pending',
                'error_message': False,
            })
            record.action_analyze_with_gemini()

    def action_analyze_with_claude(self):
        """Tương thích ngược gọi sang Gemini"""
        return self.action_analyze_with_gemini()

    def action_analyze_with_gemini(self):
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai.gemini_api_key') or os.environ.get('GEMINI_API_KEY')
        
        session = self.session_id
        topic_summary = {}
        for ans in session.answer_ids:
            top = ans.question_id.topic or 'Khác'
            if top not in topic_summary:
                topic_summary[top] = {'correct': 0, 'total': 0}
            topic_summary[top]['total'] += 1
            if ans.is_correct:
                topic_summary[top]['correct'] += 1

        if not api_key:
            # Fallback phân tích sư phạm ngoại tuyến khi chưa cấu hình API Key hoặc không có mạng
            strong_topics = [t for t, data in topic_summary.items() if data['correct'] == data['total'] and data['total'] > 0]
            weak_topics = [t for t, data in topic_summary.items() if data['correct'] < data['total']]

            strengths_text = f"• Nắm vững các chủ đề: {', '.join(strong_topics) if strong_topics else 'Cần nỗ lực thêm ở các dạng bài.'}\n• Tỷ lệ làm đúng: {session.percentage:.1f}% tổng số điểm."
            weaknesses_text = f"• Cần lưu ý các dạng toán: {', '.join(weak_topics) if weak_topics else 'Không có lỗi sai đáng kể.'}\n• Đã sai {session.wrong_count} câu trên tổng số {len(session.answer_ids)} câu."
            feedback_text = f"Học sinh {self.student_id.name} hoàn thành bài kiểm tra {session.exam_id.name} đạt {session.total_score}/{session.total_possible} điểm. Cần duy trì phong độ và rèn luyện thêm tính cẩn thận."
            suggestions_text = "1. Ôn tập kỹ các kiến thức và công thức tính toán cơ bản.\n2. Luyện tập thêm 3-5 bài tập tương tự mỗi ngày.\n3. Đọc kỹ đề bài và kiểm tra lại kết quả trước khi nộp."

            self.write({
                'strengths': strengths_text,
                'weaknesses': weaknesses_text,
                'feedback': feedback_text,
                'suggestions': suggestions_text,
                'status': 'completed',
                'analysis_date': fields.Datetime.now(),
                'error_message': 'Phân tích tự động ngoại tuyến (Để dùng Gemini AI trực tuyến, hãy cấu hình khóa ai.gemini_api_key trong Cài đặt)',
            })
            return

        self.write({'status': 'processing'})

        prompt = f"""
Bạn là một chuyên gia giáo dục và giáo viên giàu kinh nghiệm. Hãy phân tích bài thi trắc nghiệm của học sinh:
- Tên học sinh: {self.student_id.name}
- Đề thi: {session.exam_id.name}
- Điểm: {session.total_score}/{session.total_possible} ({session.percentage:.1f}%)
- Chi tiết câu đúng/sai theo dạng bài: {json.dumps(topic_summary, ensure_ascii=False)}

Hãy đưa ra nhận xét ân cần, mang tính giáo dục, chỉ ra điểm mạnh, điểm yếu và gợi ý luyện tập cụ thể.
Chỉ trả về JSON thuần túy (không kèm markdown):
{{
    "strengths": "Điểm mạnh cụ thể (dạng bài làm tốt)",
    "weaknesses": "Điểm yếu cần khắc phục (dạng bài còn sai sót)",
    "feedback": "Nhận xét sư phạm truyền cảm hứng (2-3 câu)",
    "suggestions": "Gợi ý lộ trình ôn tập và dạng bài tập cần làm thêm"
}}
"""
        model_name = self.ai_model_version or 'gemini-2.5-flash'
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        try:
            res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=25)
            if res.status_code != 200:
                # Fallback sang gemini-1.5-flash nếu model 2.5 không sẵn sàng
                fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
                res = requests.post(fallback_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=25)

            if res.status_code != 200:
                raise Exception(f"Lỗi Gemini AI ({res.status_code}): {res.text}")

            result_json = res.json()
            raw = result_json['candidates'][0]['content']['parts'][0]['text'].strip()
            data = json.loads(raw)
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
            _logger.error(f"Lỗi phân tích AI Gemini: {str(e)}")
            self.write({
                'status': 'failed',
                'error_message': str(e),
            })

    @api.model
    def cron_process_pending_analysis(self, limit=10):
        """Tác vụ định kỳ (Cron Job): Quét các bản ghi pending và tự động kích hoạt phân tích"""
        pending_records = self.search([('status', '=', 'pending')], limit=limit)
        _logger.info(f"Cron AI: Đang xử lý {len(pending_records)} bản ghi phân tích chờ...")
        for record in pending_records:
            try:
                record.action_analyze_with_gemini()
            except Exception as e:
                _logger.error(f"Cron AI: Lỗi xử lý bản ghi {record.id}: {str(e)}")