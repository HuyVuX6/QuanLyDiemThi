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
    ], default='pending', string='Trạng Thái', required=True)

    ai_model_version = fields.Char(string='Mô Hình AI', default='claude-3-sonnet-20240229')
    strengths = fields.Text(string='Điểm Mạnh (Dạng toán nắm vững)')
    weaknesses = fields.Text(string='Điểm Yếu (Dạng toán hay sai)')
    feedback = fields.Text(string='Nhận Xét Sư Phạm Chi Tiết')
    suggestions = fields.Text(string='Gợi Ý / Lộ Trình Cải Thiện')
    error_message = fields.Text(string='Thông Báo Lỗi')
    analysis_date = fields.Datetime(string='Thời Gian Phân Tích')

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
            record.action_analyze_with_claude()

    def action_analyze_with_claude(self):
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai.claude_api_key')
        
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
            # Fallback mô phỏng phân tích nội bộ khi chưa cấu hình API Key ngoài
            strong_topics = [t for t, data in topic_summary.items() if data['correct'] == data['total'] and data['total'] > 0]
            weak_topics = [t for t, data in topic_summary.items() if data['correct'] < data['total']]

            strengths_text = f"• Nắm vững các chủ đề: {', '.join(strong_topics) if strong_topics else 'Cần nỗ lực thêm ở các dạng bài.'}\n• Tỷ lệ làm đúng: {session.percentage:.1f}% tổng số điểm."
            weaknesses_text = f"• Cần lưu ý các dạng toán: {', '.join(weak_topics) if weak_topics else 'Không có lỗi sai đáng kể.'}\n• Đã sai {session.wrong_count} câu trên tổng số {len(session.answer_ids)} câu."
            feedback_text = f"Học sinh {self.student_id.name} hoàn thành bài kiểm tra {session.exam_id.name} đạt {session.total_score}/{session.total_possible} điểm. Cần duy trì phong độ và rèn luyện thêm tính cẩn thận."
            suggestions_text = "1. Ôn tập kỹ các bảng cửu chương và quy tắc tính toán cơ bản.\n2. Luyện tập thêm 3-5 bài toán có lời văn mỗi ngày.\n3. Đọc kỹ đề bài và kiểm tra lại kết quả trước khi nộp."

            self.write({
                'strengths': strengths_text,
                'weaknesses': weaknesses_text,
                'feedback': feedback_text,
                'suggestions': suggestions_text,
                'status': 'completed',
                'analysis_date': fields.Datetime.now(),
                'error_message': 'Phân tích tự động nội bộ (Để dùng Claude AI trực tiếp, hãy cấu hình khóa ai.claude_api_key trong System Parameters)',
            })
            return

        self.write({'status': 'processing'})

        prompt = f"""
Bạn là giáo viên dạy Toán lớp 3 giàu kinh nghiệm. Hãy phân tích bài thi của học sinh tiểu học:
- Tên học sinh: {self.student_id.name}
- Đề thi: {session.exam_id.name}
- Điểm: {session.total_score}/{session.total_possible} ({session.percentage:.1f}%)
- Chi tiết câu đúng/sai theo dạng toán: {json.dumps(topic_summary, ensure_ascii=False)}

Hãy đưa ra nhận xét ân cần, mang tính giáo dục, chỉ ra điểm mạnh, điểm yếu và gợi ý luyện tập cụ thể cho học sinh lớp 3.
Chỉ trả về định dạng JSON thuần túy (không kèm markdown):
{{
    "strengths": "Điểm mạnh cụ thể (dạng toán học tốt)",
    "weaknesses": "Điểm yếu cần khắc phục (dạng toán còn nhầm lẫn)",
    "feedback": "Nhận xét sư phạm truyền cảm hứng (2-3 câu)",
    "suggestions": "Gợi ý lộ trình ôn tập và dạng bài tập cần làm thêm"
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
            _logger.error(f"Lỗi phân tích AI: {str(e)}")
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
                record.action_analyze_with_claude()
            except Exception as e:
                _logger.error(f"Cron AI: Lỗi xử lý bản ghi {record.id}: {str(e)}")