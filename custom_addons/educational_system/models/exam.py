# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions

class ExamExam(models.Model):
    _name = 'exam.exam'
    _description = 'Đề Thi'
    _rec_name = 'name'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã đề thi phải duy nhất!'),
        ('total_score_pos', 'CHECK(total_score > 0)', 'Tổng điểm đề thi phải > 0!'),
    ]

    code = fields.Char(string='Mã Đề Thi', required=True, size=30)
    name = fields.Char(string='Tên Đề Thi', required=True, size=255)
    exam_type = fields.Selection([
        ('QuickTest', 'Kiểm Tra 15 Phút'),
        ('MidTerm', 'Kiểm Tra Giữa Kỳ'),
        ('FinalTerm', 'Kiểm Tra Cuối Kỳ')
    ], string='Loại Đề Thi', default='QuickTest')
    total_score = fields.Float(string='Tổng Điểm', default=10.0, required=True)
    time_limit_minutes = fields.Integer(string='Thời Gian (Phút)', default=15)
    question_ids = fields.Many2many(
        comodel_name='exam.question',
        relation='exam_exam_question_rel',
        column1='exam_id',
        column2='question_id',
        string='Ngân Hàng Câu Hỏi'
    )

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"


class ExamQuestion(models.Model):
    _name = 'exam.question'
    _description = 'Câu Hỏi Toán Lớp 3'
    _rec_name = 'content'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã câu hỏi phải duy nhất!'),
        ('points_pos', 'CHECK(points > 0)', 'Điểm câu hỏi phải > 0!'),
    ]

    code = fields.Char(string='Mã Câu Hỏi', required=True, size=30)
    content = fields.Text(string='Nội Dung Câu Hỏi', required=True)
    correct_answer = fields.Char(string='Đáp Án Đúng', required=True)
    points = fields.Float(string='Điểm', default=1.0, required=True)
    topic = fields.Selection([
        ('Addition', 'Phép Cộng'),
        ('Subtraction', 'Phép Trừ'),
        ('Multiplication', 'Phép Nhân'),
        ('Division', 'Phép Chia'),
        ('Geometry', 'Hình Học'),
        ('WordProblem', 'Toán Lời Văn'),
    ], string='Chủ Đề Toán', required=True)
    difficulty = fields.Selection([
        ('Easy', 'Dễ'),
        ('Medium', 'Trung Bình'),
        ('Hard', 'Khó')
    ], string='Độ Khó', default='Medium')

    def _compute_display_name(self):
        for record in self:
            short_c = record.content[:35] if record.content else ''
            record.display_name = f"[{record.code}] {short_c}..."


class ExamSession(models.Model):
    _name = 'exam.session'
    _description = 'Lượt Làm Bài Của Học Sinh'
    _rec_name = 'name'

    _sql_constraints = [
        ('unique_student_exam', 'UNIQUE(student_id, exam_id)', 'Mỗi học sinh chỉ làm bài thi này 1 lần!'),
    ]

    name = fields.Char(compute='_compute_name', store=True, string='Tên Phiên')
    student_id = fields.Many2one('school.student', string='Học Sinh', required=True, ondelete='cascade')
    exam_id = fields.Many2one('exam.exam', string='Đề Thi', required=True, ondelete='cascade')
    class_id = fields.Many2one('school.class', string='Lớp (Snapshot)', required=True, ondelete='restrict')
    start_time = fields.Datetime(string='Bắt Đầu', default=fields.Datetime.now)
    end_time = fields.Datetime(string='Nộp Bài')
    status = fields.Selection([
        ('NotStarted', 'Chưa Bắt Đầu'),
        ('InProgress', 'Đang Làm'),
        ('Submitted', 'Đã Nộp'),
        ('Graded', 'Đã Chấm'),
    ], default='InProgress', string='Trạng Thái')

    total_possible = fields.Float(
        string='Tổng Điểm Tối Đa',
        related='exam_id.total_score',
        store=True
    )
    total_score = fields.Float(
        string='Điểm Đạt Được',
        compute='_compute_scores',
        store=True
    )
    correct_count = fields.Integer(
        string='Số Câu Đúng',
        compute='_compute_scores',
        store=True
    )
    percentage = fields.Float(
        string='Tỷ Lệ (%)',
        compute='_compute_scores',
        store=True
    )

    answer_ids = fields.One2many('exam.answer', 'session_id', string='Chi Tiết Bài Làm')
    analysis_ids = fields.One2many('ai.analysis', 'session_id', string='Kết Quả AI')

    @api.depends('student_id.name', 'exam_id.name')
    def _compute_name(self):
        for record in self:
            record.name = f"{record.student_id.name or ''} - {record.exam_id.name or ''}"

    @api.depends('answer_ids.points_earned', 'answer_ids.is_correct', 'total_possible')
    def _compute_scores(self):
        for record in self:
            answers = record.answer_ids
            record.total_score = sum(ans.points_earned for ans in answers)
            record.correct_count = len(answers.filtered(lambda a: a.is_correct))
            if record.total_possible and record.total_possible > 0:
                record.percentage = (record.total_score / record.total_possible) * 100.0
            else:
                record.percentage = 0.0

    def action_submit_exam(self):
        self.ensure_one()
        self.end_time = fields.Datetime.now()
        self.status = 'Submitted'
        self.env['ai.analysis'].create({
            'session_id': self.id,
            'student_id': self.student_id.id,
            'status': 'pending',
        })


class ExamAnswer(models.Model):
    _name = 'exam.answer'
    _description = 'Chi Tiết Đáp Án'

    _sql_constraints = [
        ('unique_session_question', 'UNIQUE(session_id, question_id)', 'Một câu hỏi chỉ được trả lời 1 lần!'),
    ]

    session_id = fields.Many2one('exam.session', string='Phiên Thi', required=True, ondelete='cascade')
    question_id = fields.Many2one('exam.question', string='Câu Hỏi', required=True, ondelete='cascade')
    answer_given = fields.Char(string='Đáp Án Của Học Sinh')
    is_correct = fields.Boolean(string='Đúng/Sai', compute='_compute_evaluation', store=True)
    points_earned = fields.Float(string='Điểm Nhận Được', compute='_compute_evaluation', store=True)

    @api.depends('answer_given', 'question_id.correct_answer', 'question_id.points')
    def _compute_evaluation(self):
        for record in self:
            if record.answer_given and record.question_id.correct_answer:
                s_ans = str(record.answer_given).strip().lower()
                c_ans = str(record.question_id.correct_answer).strip().lower()
                if s_ans == c_ans:
                    record.is_correct = True
                    record.points_earned = record.question_id.points
                    continue
            record.is_correct = False
            record.points_earned = 0.0