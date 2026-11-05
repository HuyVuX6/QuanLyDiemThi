# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions, Command
from datetime import timedelta
import ast
import base64
import html
import io
import json
import logging
import operator
import os
import re
import openpyxl
from ..utils import omr_engine

_logger = logging.getLogger(__name__)

# Bảng toán tử an toàn cho phép tính biểu thức toán học (thay thế eval chống RCE)
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
}


def safe_eval_math_expression(expr_str):
    """Tính giá trị biểu thức số học an toàn bằng AST, tuyệt đối không dùng eval()"""
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in SAFE_OPERATORS:
                left = _eval(node.left)
                right = _eval(node.right)
                if op_type in (ast.Div, ast.FloorDiv) and right == 0:
                    raise ZeroDivisionError("Chia cho 0")
                return SAFE_OPERATORS[op_type](left, right)
            raise ValueError(f"Toán tử không hỗ trợ: {op_type.__name__}")
        elif isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_OPERATORS:
            return SAFE_OPERATORS[type(node.op)](_eval(node.operand))
        raise TypeError(f"Biểu thức không hợp lệ: {type(node).__name__}")

    clean_expr = expr_str.replace('×', '*').replace(':', '/').replace('x', '*').replace('X', '*')
    parsed = ast.parse(clean_expr, mode='eval')
    res = _eval(parsed)
    if isinstance(res, float) and res.is_integer():
        return int(res)
    return round(res, 2) if isinstance(res, float) else res


class ExamExam(models.Model):
    _name = 'exam.exam'
    _description = 'Đề Thi'
    _rec_name = 'name'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã đề thi phải duy nhất!'),
        ('total_score_pos', 'CHECK(total_score > 0)', 'Tổng điểm đề thi phải > 0!'),
    ]

    @api.model
    def _default_grade_id(self):
        grade = self.env['school.grade'].search([('code', '=', 'KHOI_3')], limit=1)
        if not grade:
            grade = self.env['school.grade'].search([('status', '=', 'active')], limit=1)
        return grade.id if grade else False

    code = fields.Char(string='Mã Đề Thi (6 số)', required=True, size=6, help='Mã đề gồm 6 chữ số (0-9) tương ứng với mục 8 trên Phiếu OMR')
    name = fields.Char(string='Tên Đề Thi', required=True, size=255)
    grade_id = fields.Many2one(
        'school.grade',
        string='Khối Lớp',
        default=_default_grade_id,
        ondelete='restrict',
        index=True,
        help='Khối lớp áp dụng của đề thi (ví dụ: KHOI_1, KHOI_2, KHOI_3...)'
    )
    exam_type = fields.Selection([
        ('QuickTest', 'Kiểm Tra Thường Xuyên (15 Phút)'),
        ('MidTerm', 'Kiểm Tra Giữa Kỳ'),
        ('FinalTerm', 'Kiểm Tra Cuối Kỳ')
    ], string='Loại Đề Thi', default='QuickTest', required=True)
    topic = fields.Char(string='Chủ Đề Kiến Thức', default='Tổng hợp Toán tiểu học')
    status = fields.Selection([
        ('active', 'Đang Hoạt Động'),
        ('closed', 'Đã Đóng')
    ], string='Trạng Thái', default='active', required=True)
    auto_analyze = fields.Boolean(
        string='Tự Động Phân Tích AI',
        default=True,
        help='Tự động tạo bản phân tích AI ngay sau khi chấm bài'
    )
    total_score = fields.Float(string='Tổng Điểm', default=10.0, required=True)
    time_limit_minutes = fields.Integer(string='Thời Gian (Phút)', default=35)
    question_ids = fields.Many2many(
        comodel_name='exam.question',
        relation='exam_exam_question_rel',
        column1='exam_id',
        column2='question_id',
        string='Ngân Hàng Câu Hỏi Trong Đề',
        domain="[('grade_id', 'in', [grade_id, False])]"
    )
    total_questions = fields.Integer(
        string='Tổng Số Câu Hỏi',
        compute='_compute_total_questions',
        store=True
    )
    session_ids = fields.One2many('exam.session', 'exam_id', string='Các Lượt Làm Bài')

    @api.constrains('code')
    def _check_exam_code(self):
        for record in self:
            if record.code:
                clean_code = str(record.code).strip()
                if not re.match(r'^\d{5,6}$', clean_code):
                    raise exceptions.ValidationError(
                        f"Mã đề thi '{record.code}' không hợp lệ! Mã đề thi phải gồm 5 đến 6 chữ số (chỉ bao gồm chữ số 0-9) để khớp với 6 cột tô Mã đề trên phiếu trả lời trắc nghiệm OMR."
                    )

    @api.depends('question_ids')
    def _compute_total_questions(self):
        for record in self:
            record.total_questions = len(record.question_ids)

    def _compute_display_name(self):
        for record in self:
            grade_str = f" ({record.grade_id.code})" if record.grade_id else ""
            record.display_name = f"[{record.code}] {record.name}{grade_str}"

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        if name:
            domain = [
                '|', '|', '|',
                ('name', operator, name),
                ('code', operator, name),
                ('question_ids.content', operator, name),
                ('question_ids.code', operator, name)
            ] + domain
        return self._search(domain, limit=limit, order=order)

    def action_open_assign_wizard(self):
        """Mở cửa sổ Wizard để tạo nhanh đợt kiểm tra cho lớp học từ đề thi này"""
        self.ensure_one()
        if self.status != 'active':
            raise exceptions.UserError("Đề thi này đã đóng hoặc chưa kích hoạt, không thể giao đề cho lớp!")
        return {
            'name': f'Giao Đề Kiểm Tra Cho Lớp: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_exam_id': self.id,
            }
        }

    def action_open_add_calculation_wizard(self):
        """Mở cửa sổ Wizard thêm phép tính trực tiếp vào đề thi trên Odoo"""
        self.ensure_one()
        return {
            'name': f'Thêm Phép Tính Trực Tiếp Vào Đề: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.add.calculation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_exam_id': self.id,
                'default_grade_id': self.grade_id.id if self.grade_id else False,
            }
        }

    def action_delete_exam(self):
        """Xóa bài kiểm tra / đề thi này và xóa toàn bộ điểm số học sinh liên quan"""
        self.ensure_one()
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã xóa bài kiểm tra',
                'message': 'Đã xóa bài kiểm tra thành công. Toàn bộ điểm số liên quan đã được xóa sạch.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }

    def unlink(self):
        # Lấy danh sách học sinh liên quan từ tất cả các phiên thi của đề này
        sessions = self.env['exam.session'].search([('exam_id', 'in', self.ids)])
        students = sessions.mapped('student_id')
        batches = self.env['exam.batch'].search([('exam_id', 'in', self.ids)])
        if batches:
            batches.unlink()
        if sessions.exists():
            sessions.unlink()
        res = super().unlink()
        # Ép tính lại điểm tích lũy của học sinh để điểm số bị xóa theo không lưu lại kết quả
        if students.exists():
            students._compute_student_exam_stats()
        return res


class ExamQuestion(models.Model):
    _name = 'exam.question'
    _description = 'Ngân Hàng Câu Hỏi Theo Khối'
    _rec_name = 'content'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã câu hỏi phải duy nhất!'),
        ('points_pos', 'CHECK(points > 0)', 'Điểm câu hỏi phải > 0!'),
    ]

    @api.model
    def _default_grade_id(self):
        grade = self.env['school.grade'].search([('code', '=', 'KHOI_3')], limit=1)
        if not grade:
            grade = self.env['school.grade'].search([('status', '=', 'active')], limit=1)
        return grade.id if grade else False

    def _default_question_code(self):
        import time, random
        return f"CH-PT-{time.strftime('%y%m%d%H%M%S')}-{random.randint(10, 99)}"

    code = fields.Char(string='Mã Câu Hỏi', required=True, size=30, default=_default_question_code)
    grade_id = fields.Many2one(
        'school.grade',
        string='Khối Lớp',
        default=_default_grade_id,
        ondelete='restrict',
        index=True,
        help='Khối lớp của câu hỏi (ví dụ: KHOI_1, KHOI_2, KHOI_3...)'
    )
    content = fields.Text(string='Nội Dung Câu Hỏi', required=True)
    question_type = fields.Selection([
        ('single_choice', 'Trắc Nghiệm (A, B, C, D)'),
    ], string='Dạng Câu Hỏi', default='single_choice', required=True)
    option_a = fields.Char(string='Phương Án A', required=True, default='')
    option_b = fields.Char(string='Phương Án B', required=True, default='')
    option_c = fields.Char(string='Phương Án C', required=True, default='')
    option_d = fields.Char(string='Phương Án D', required=True, default='')
    correct_answer = fields.Selection([
        ('A', 'A'),
        ('B', 'B'),
        ('C', 'C'),
        ('D', 'D'),
    ], string='Đáp Án Đúng (*)', default='A', required=True)
    acceptable_answers = fields.Char(string='Ghi Chú Đáp Án')
    tolerance = fields.Float(string='Dung Sai', default=0.0)
    points = fields.Float(string='Điểm', default=1.0, required=True)
    topic = fields.Selection([
        ('Addition', 'Phép Cộng'),
        ('Subtraction', 'Phép Trừ'),
        ('Multiplication', 'Phép Nhân'),
        ('Division', 'Phép Chia'),
        ('MixedOperation', 'Biểu Thức / Phép Tính Hỗn Hợp'),
        ('FindX', 'Tìm Thành Phần Chưa Biết (Tìm x)'),
        ('Geometry', 'Hình Học'),
        ('WordProblem', 'Toán Lời Văn'),
    ], string='Chủ Đề Toán', required=True)
    difficulty = fields.Selection([
        ('Easy', 'Dễ'),
        ('Medium', 'Trung Bình'),
        ('Hard', 'Khó')
    ], string='Độ Khó', default='Medium', required=True)
    explanation = fields.Text(string='Hướng Dẫn Giải / Lời Giải Chi Tiết')

    full_content = fields.Text(string='Đề Bài Đầy Đủ', compute='_compute_full_content', store=True)

    @api.depends('content', 'option_a', 'option_b', 'option_c', 'option_d')
    def _compute_full_content(self):
        for record in self:
            opts = []
            if record.option_a:
                opts.append(f"A. {record.option_a}")
            if record.option_b:
                opts.append(f"B. {record.option_b}")
            if record.option_c:
                opts.append(f"C. {record.option_c}")
            if record.option_d:
                opts.append(f"D. {record.option_d}")
            opts_str = " | ".join(opts)
            record.full_content = f"{record.content}\n{opts_str}" if opts_str else (record.content or '')

    @api.constrains('correct_answer')
    def _check_correct_answer(self):
        for record in self:
            if record.correct_answer and record.correct_answer.upper() not in ['A', 'B', 'C', 'D']:
                raise exceptions.ValidationError("Đáp án đúng của câu hỏi trắc nghiệm phải là một trong các phương án: A, B, C hoặc D!")

    def _compute_display_name(self):
        for record in self:
            short_c = record.content[:45] if record.content else ''
            record.display_name = f"[{record.code}] {short_c}..."

    def action_open_import_wizard(self):
        """Mở Wizard Import Câu Hỏi Từ File Excel"""
        return {
            'name': 'Import Ngân Hàng Câu Hỏi Từ Excel',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.question.import.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_add_calculation_wizard(self):
        """Mở Wizard Thêm Phép Tính Trực Tiếp Vào Ngân Hàng Câu Hỏi"""
        return {
            'name': 'Thêm Phép Tính Trực Tiếp Vào Ngân Hàng Câu Hỏi',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.add.calculation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {}
        }


class ExamBatch(models.Model):
    _name = 'exam.batch'
    _description = 'Đợt Kiểm Tra Của Lớp'
    _order = 'date desc, id desc'
    _rec_name = 'name'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã đợt kiểm tra phải là duy nhất!'),
    ]

    code = fields.Char(string='Mã Đợt', required=True, size=50)
    name = fields.Char(string='Tên Đợt Kiểm Tra', required=True, size=255)
    class_id = fields.Many2one('school.class', string='Lớp Học', required=True, ondelete='cascade', index=True)
    grade_id = fields.Many2one('school.grade', string='Khối Lớp', related='class_id.grade_id', store=True, readonly=True)
    batch_type = fields.Selection([
        ('entry', 'Kiểm Tra Đầu Kỳ / Khảo Sát'),
        ('midterm', 'Kiểm Tra Giữa Kỳ'),
        ('final', 'Kiểm Tra Cuối Kỳ'),
        ('regular', 'Kiểm Tra Thường Xuyên'),
        ('retest', 'Thi Lại / Bổ Sung (Dành Cho HS Rớt)'),
    ], string='Đợt Kiểm Tra', default='midterm', required=True)
    exam_id = fields.Many2one(
        'exam.exam',
        string='Đề Thi Áp Dụng',
        required=True,
        domain="[('status', '=', 'active'), '|', ('grade_id', '=', grade_id), ('grade_id', '=', False)]",
        ondelete='restrict'
    )
    date = fields.Date(string='Ngày Kiểm Tra', default=fields.Date.today, required=True)
    start_datetime = fields.Datetime(
        string='Thời Gian Bắt Đầu',
        default=fields.Datetime.now,
        required=True
    )
    end_datetime = fields.Datetime(
        string='Thời Gian Kết Thúc / Hạn Chót',
        required=True,
        default=lambda self: fields.Datetime.now() + timedelta(days=1),
        help='Thời điểm hết hạn đợt kiểm tra. Khi quá thời gian này, đợt thi sẽ tự động bị khóa.'
    )
    is_expired = fields.Boolean(
        string='Đã Hết Hạn',
        compute='_compute_is_expired',
        store=True,
        help='Tự động xác định đợt kiểm tra đã quá thời gian kết thúc hay chưa'
    )
    delivery_mode = fields.Selection([
        ('offline', 'Thi Trực Tiếp Trên Giấy (OMR)'),
    ], string='Thể Thức Thi', default='offline', required=True)
    status = fields.Selection([
        ('draft', 'Tạo Đề & Cấp SBD'),
        ('in_progress', 'Đang Diễn Ra (Cho Phép Tải File RAR Chấm Bài)'),
        ('completed', 'Đã Hoàn Thành & Chấm Điểm'),
    ], string='Trạng Thái', default='draft', required=True)

    parent_batch_id = fields.Many2one('exam.batch', string='Thuộc Đợt Gốc', ondelete='set null', help='Đợt kiểm tra gốc nếu đây là đợt thi lại')
    retest_batch_ids = fields.One2many('exam.batch', 'parent_batch_id', string='Các Đợt Thi Lại')

    session_ids = fields.One2many('exam.session', 'batch_id', string='Danh Sách Thí Sinh & Số Báo Danh')

    total_students = fields.Integer(string='Tổng Sĩ Số', compute='_compute_batch_stats', store=True)
    graded_count = fields.Integer(string='Đã Chấm', compute='_compute_batch_stats', store=True)
    passed_count = fields.Integer(string='Số Đạt', compute='_compute_batch_stats', store=True)
    failed_count = fields.Integer(string='Số Rớt', compute='_compute_batch_stats', store=True)
    pass_rate = fields.Float(string='Tỷ Lệ Đạt', compute='_compute_batch_stats', store=True)
    average_score = fields.Float(string='ĐiểmTB', compute='_compute_batch_stats', store=True)
    note = fields.Text(string='Ghi Chú')

    @staticmethod
    def _format_six_digit_sbd(student_code, fallback_idx, used_sbds):
        """
        Sinh Số Báo Danh chuẩn 6 chữ số (0-9) tương ứng với 6 cột mục '7. Số báo danh' trên Phiếu OMR.
        Ưu tiên lấy phần số từ mã học sinh (ví dụ HS001 -> 000001), nếu trùng hoặc không có số thì tăng tuần tự.
        """
        digits = re.sub(r'\D', '', str(student_code or ''))
        if digits:
            candidate = digits.zfill(6)[-6:]
            if candidate != '000000' and candidate not in used_sbds:
                used_sbds.add(candidate)
                return candidate
        num = max(1, int(fallback_idx))
        while True:
            cand = str(num).zfill(6)[-6:]
            if cand not in used_sbds:
                used_sbds.add(cand)
                return cand
            num += 1

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Tự động lập danh sách học sinh và cấp Số Báo Danh (6 chữ số) ngay khi tạo đợt kiểm tra
        for record in records:
            if record.class_id and record.exam_id and not record.session_ids and record.batch_type != 'retest':
                record._auto_populate_students_with_sbd()
        return records

    def _auto_populate_students_with_sbd(self):
        """Khởi tạo danh sách thí sinh trong lớp và cấp Số Báo Danh 6 chữ số cho từng học sinh"""
        self.ensure_one()
        if not self.class_id or not self.exam_id:
            return 0
        active_students = self.class_id.student_ids.filtered(lambda s: s.status == 'Active').sorted(key=lambda s: s.code or s.name)
        if not active_students:
            active_students = self.class_id.student_ids.sorted(key=lambda s: s.code or s.name)

        existing_sessions = self.session_ids
        existing_student_ids = existing_sessions.mapped('student_id.id')
        used_sbds = set(s.sbd for s in existing_sessions if s.sbd)

        # Cấp SBD cho những phiên đã có nhưng chưa có SBD
        for idx, sess in enumerate(existing_sessions, start=1):
            if not sess.sbd or len(sess.sbd) != 6:
                sbd_val = self._format_six_digit_sbd(sess.student_id.code, idx, used_sbds)
                sess.sbd = sbd_val

        new_sessions = []
        seq = len(existing_sessions) + 1
        for student in active_students:
            if student.id not in existing_student_ids:
                sbd_val = self._format_six_digit_sbd(student.code, seq, used_sbds)
                new_sessions.append({
                    'batch_id': self.id,
                    'student_id': student.id,
                    'class_id': self.class_id.id,
                    'exam_id': self.exam_id.id,
                    'sbd': sbd_val,
                    'status': 'NotStarted',
                })
                seq += 1
        if new_sessions:
            self.env['exam.session'].create(new_sessions)
        return len(new_sessions)

    @api.model
    def cron_check_and_close_expired_batches(self):
        """Tự động kiểm tra và chuyển các đợt thi đã hết hạn sang trạng thái Đã Hoàn Thành"""
        now = fields.Datetime.now()
        expired_batches = self.search([
            ('end_datetime', '<=', now),
            ('status', '!=', 'completed'),
        ])
        if expired_batches:
            expired_batches.write({'status': 'completed'})

    @api.depends('end_datetime')
    def _compute_is_expired(self):
        now = fields.Datetime.now()
        for record in self:
            record.is_expired = bool(record.end_datetime and now >= record.end_datetime)

    @api.onchange('end_datetime')
    def _onchange_end_datetime(self):
        now = fields.Datetime.now()
        if self.end_datetime:
            if self.end_datetime > now:
                self.is_expired = False
                if self.status == 'completed':
                    self.status = 'in_progress'
            else:
                self.is_expired = True
                self.status = 'completed'

    def write(self, vals):
        now = fields.Datetime.now()
        if 'end_datetime' in vals and vals.get('end_datetime'):
            end_dt = fields.Datetime.from_string(vals['end_datetime']) if isinstance(vals['end_datetime'], str) else vals['end_datetime']
            if end_dt:
                if end_dt > now:
                    if 'status' not in vals:
                        for record in self:
                            if record.status == 'completed':
                                super(ExamBatch, record).write({'status': 'in_progress'})
                else:
                    if 'status' not in vals:
                        for record in self:
                            if record.status in ('draft', 'in_progress'):
                                super(ExamBatch, record).write({'status': 'completed'})
        return super().write(vals)

    @api.constrains('start_datetime', 'end_datetime')
    def _check_batch_datetimes(self):
        for record in self:
            if record.start_datetime and record.end_datetime and record.end_datetime < record.start_datetime:
                raise exceptions.ValidationError("Thời gian kết thúc / hạn chót phải sau thời gian bắt đầu đợt kiểm tra!")

    @api.onchange('class_id', 'batch_type')
    def _onchange_suggest_name(self):
        if self.class_id and self.batch_type:
            type_dict = dict(self._fields['batch_type'].selection)
            type_name = type_dict.get(self.batch_type, 'Kiểm Tra')
            if not self.name:
                self.name = f"{type_name} - {self.class_id.name}"
            if not self.code:
                type_code_map = {'entry': 'DK', 'midterm': 'GK', 'final': 'CK', 'regular': 'TX', 'retest': 'TL'}
                prefix = type_code_map.get(self.batch_type, 'KT')
                self.code = f"{prefix}-{self.class_id.code or 'LOP'}-{fields.Date.today().strftime('%Y%m')}"

    @api.depends('session_ids', 'session_ids.status', 'session_ids.total_score', 'session_ids.passed')
    def _compute_batch_stats(self):
        for record in self:
            sessions = record.session_ids
            record.total_students = len(sessions)
            graded = sessions.filtered(lambda s: s.status == 'Graded')
            record.graded_count = len(graded)
            if graded:
                passed = graded.filtered(lambda s: s.passed)
                failed = graded.filtered(lambda s: not s.passed)
                record.passed_count = len(passed)
                record.failed_count = len(failed)
                record.pass_rate = round((len(passed) / len(graded)) * 100.0, 1)
                record.average_score = round(sum(s.total_score for s in graded) / len(graded), 2)
            else:
                record.passed_count = 0
                record.failed_count = 0
                record.pass_rate = 0.0
                record.average_score = 0.0

    def action_populate_students(self):
        """Tự động cập nhật danh sách học sinh trong lớp và cấp Số Báo Danh (6 chữ số)"""
        self.ensure_one()
        if not self.class_id:
            raise exceptions.UserError("Vui lòng chọn lớp học trước khi lập danh sách học sinh!")
        if not self.exam_id:
            raise exceptions.UserError("Vui lòng chọn đề thi áp dụng trước khi lập danh sách học sinh!")
        if not self.class_id.student_ids:
            raise exceptions.UserError(f"Lớp {self.class_id.name} hiện chưa có học sinh nào. Vui lòng thêm học sinh vào lớp trước!")

        created_count = self._auto_populate_students_with_sbd()
        message = (
            f"Đã lập danh sách và cấp Số Báo Danh (6 số) cho {created_count} học sinh mới!"
            if created_count
            else "Tất cả học sinh trong lớp đã có mặt và được cấp Số Báo Danh (6 chữ số) đầy đủ."
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Cấp Số Báo Danh Thành Công',
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_create_retest_batch(self):
        """Tạo một đợt thi lại cho các học sinh bị rớt (điểm < 5.0) trong đợt này"""
        self.ensure_one()
        failed_sessions = self.session_ids.filtered(lambda s: s.status == 'Graded' and not s.passed)
        if not failed_sessions:
            raise exceptions.UserError(
                f"Đợt kiểm tra '{self.name}' hiện không có học sinh nào bị rớt (hoặc chưa chấm bài xong)!\n"
                f"Chỉ có thể tạo đợt thi lại cho học sinh có điểm dưới 5.0."
            )

        retest_count = len(self.retest_batch_ids) + 1
        retest_code = f"{self.code}-TL{retest_count}"
        retest_name = f"Thi Lại (Lần {retest_count}) - {self.name}"

        retest_batch = self.create({
            'code': retest_code,
            'name': retest_name,
            'class_id': self.class_id.id,
            'batch_type': 'retest',
            'exam_id': self.exam_id.id,
            'parent_batch_id': self.id,
            'date': fields.Date.today(),
            'start_datetime': fields.Datetime.now(),
            'end_datetime': fields.Datetime.now() + timedelta(days=2),
            'delivery_mode': self.delivery_mode,
            'status': 'in_progress',
        })

        used_sbds = set()
        retest_sessions = []
        for idx, s in enumerate(failed_sessions, start=1):
            sbd_val = self._format_six_digit_sbd(s.sbd or s.student_id.code, idx, used_sbds)
            retest_sessions.append({
                'batch_id': retest_batch.id,
                'student_id': s.student_id.id,
                'class_id': self.class_id.id,
                'exam_id': self.exam_id.id,
                'sbd': sbd_val,
                'status': 'NotStarted',
            })
        self.env['exam.session'].create(retest_sessions)

        return {
            'name': f"Đợt Thi Lại Cho Học Sinh Rớt: {retest_name}",
            'type': 'ir.actions.act_window',
            'res_model': 'exam.batch',
            'res_id': retest_batch.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_exam_paper(self):
        """In đề thi trắc nghiệm A4 để phát cho học sinh thi offline"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/educational_system/print_exam_paper/{self.id}",
            'target': 'new',
        }

    def action_print_answer_sheet_blank(self):
        """Tải về file PDF phiếu trả lời trắc nghiệm chuẩn OMR trống (50 câu) để in/photocopy"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/educational_system/download_answer_sheet/{self.id}?mode=blank",
            'target': 'self',
        }

    def action_download_sample_rar(self):
        """Tải về tệp nén .RAR mẫu chứa ảnh phiếu trả lời trắc nghiệm đã tô sẵn SBD, Mã đề và đáp án của cả lớp"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/educational_system/download_batch_sample_rar/{self.id}",
            'target': 'self',
        }

    def action_start_batch(self):
        """Bắt đầu đợt kiểm tra (chuyển trạng thái sang Đang Diễn Ra)"""
        now = fields.Datetime.now()
        for record in self:
            if not record.session_ids:
                record._auto_populate_students_with_sbd()
            if not record.session_ids:
                raise exceptions.UserError(
                    "Lớp học chưa có học sinh nào trong danh sách thi! "
                    "Vui lòng thêm học sinh vào lớp và nhấn 'Lập Danh Sách & Cấp SBD' trước khi bắt đầu."
                )
            if record.end_datetime and record.end_datetime <= now:
                raise exceptions.UserError(
                    "Thời gian kết thúc / hạn chót của đợt thi đã qua! "
                    "Vui lòng chỉnh lại thời gian kết thúc sang tương lai trước khi bắt đầu."
                )
            record.write({'status': 'in_progress'})

    def action_finish_batch(self):
        """Hoàn tất đợt kiểm tra (chuyển sang Hoàn thành)"""
        self.ensure_one()
        if self.status != 'in_progress':
            raise exceptions.UserError("Chỉ có thể hoàn tất đợt kiểm tra khi đang ở trạng thái 'Đang Diễn Ra'!")

        ungraded_sessions = self.session_ids.filtered(lambda s: s.status != 'Graded')
        if not ungraded_sessions:
            self.write({'status': 'completed'})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Hoàn Tất Đợt Thi',
                    'message': f"Đợt kiểm tra {self.name} đã được hoàn tất thành công! Toàn bộ {len(self.session_ids)} học sinh đã được chấm điểm.",
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'}
                }
            }
        else:
            return {
                'name': 'Xác Nhận Hoàn Tất Đợt Kiểm Tra',
                'type': 'ir.actions.act_window',
                'res_model': 'exam.batch.finish.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_batch_id': self.id,
                }
            }

    def action_open_batch_scan_wizard(self):
        """Mở cửa sổ tải lên tệp nén .RAR / .ZIP chứa toàn bộ ảnh bài thi của lớp để chấm điểm tự động theo SBD"""
        self.ensure_one()
        if self.status != 'in_progress':
            raise exceptions.UserError("Chức năng chấm bài bằng file nén RAR chỉ khả dụng khi đợt kiểm tra ở trạng thái 'Đang Diễn Ra'!")
        if not self.session_ids:
            self._auto_populate_students_with_sbd()
        return {
            'name': f"Chấm Bài Hàng Loạt Qua Tệp Nén (.RAR) - {self.name}",
            'type': 'ir.actions.act_window',
            'res_model': 'exam.batch.scan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
            }
        }

    def action_delete_batch(self):
        """Xóa bài kiểm tra này và xóa hoàn toàn điểm số của học sinh liên quan"""
        self.ensure_one()
        class_id = self.class_id.id if self.class_id else False
        self.unlink()
        if class_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'school.class',
                'res_id': class_id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã xóa bài kiểm tra',
                'message': 'Đã xóa bài kiểm tra thành công. Toàn bộ điểm số liên quan của học sinh đã được làm mới.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }

    def unlink(self):
        # Thu thập danh sách học sinh liên quan trước khi xóa để tính toán lại điểm số
        students = self.mapped('session_ids.student_id')
        # Xóa tất cả các bài làm (sessions) của bài kiểm tra này
        sessions = self.mapped('session_ids')
        sessions.unlink()
        res = super().unlink()
        # Điểm của học sinh khi bài kiểm tra đó bị xóa sẽ bị xóa theo không lưu lại kết quả
        if students.exists():
            students._compute_student_exam_stats()
        return res


class ExamSession(models.Model):
    _name = 'exam.session'
    _description = 'Kết Quả Bài Kiểm Tra Của Học Sinh'
    _order = 'sbd asc, id desc'
    _rec_name = 'name'

    _sql_constraints = [
        ('unique_student_batch', 'UNIQUE(student_id, batch_id)', 'Mỗi học sinh chỉ có 1 bài thi trong cùng một đợt kiểm tra!'),
        ('unique_batch_sbd', 'UNIQUE(batch_id, sbd)', 'Số báo danh (SBD) không được trùng nhau trong cùng một đợt kiểm tra!'),
    ]

    name = fields.Char(compute='_compute_name', store=True, string='Tên Phiên')
    batch_id = fields.Many2one('exam.batch', string='Đợt Kiểm Tra', ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', string='Học Sinh', required=True, ondelete='cascade', index=True)
    student_code = fields.Char(related='student_id.code', string='Mã Học Sinh', store=True, readonly=True)
    student_name = fields.Char(related='student_id.name', string='Họ Và Tên Học Sinh', store=True, readonly=True)
    grade_id = fields.Many2one('school.grade', related='student_id.grade_id', string='Khối Lớp', store=True, readonly=True)
    sbd = fields.Char(
        string='Số Báo Danh (6 số)',
        size=6,
        index=True,
        copy=False,
        help='Số báo danh gồm 6 chữ số (ví dụ: 000001) cấp cho học sinh để tô vào mục 7 trên Phiếu trả lời trắc nghiệm OMR'
    )
    exam_id = fields.Many2one(
        'exam.exam',
        string='Đề Thi',
        required=True,
        domain=[('status', '=', 'active')],
        ondelete='cascade'
    )
    time_limit_minutes = fields.Integer(
        string='Thời Gian Làm Bài (Phút)',
        related='exam_id.time_limit_minutes',
        readonly=True
    )
    # Lưu lớp tại thời điểm thi (không phụ thuộc động vào student_id.class_id để khi học sinh chuyển lớp lịch sử vẫn chính xác)
    class_id = fields.Many2one(
        'school.class',
        string='Lớp Lúc Thi',
        ondelete='restrict',
        index=True
    )
    start_time = fields.Datetime(string='Thời Gian Bắt Đầu')
    end_time = fields.Datetime(string='Thời Gian Chấm Điểm')
    status = fields.Selection([
        ('NotStarted', 'Không làm bài'),
        ('Graded', 'Đã Chấm Điểm'),
    ], default='NotStarted', string='Trạng Thái', required=True)
    auto_analyze = fields.Boolean(
        string='Tự Động Phân Tích AI',
        default=True
    )

    scanned_image = fields.Binary(string='Ảnh Phiếu Trắc Nghiệm Đã Quét', attachment=True)
    scanned_image_filename = fields.Char(string='Tên Tệp Ảnh Trong File RAR')
    scan_date = fields.Datetime(string='Thời Gian Quét / Chấm')
    ocr_detected_answers = fields.Text(string='Kết Quả Nhận Diện Ô Tô')
    detected_student_code = fields.Char(string='SBD Quét Được (Mục 7)')
    detected_exam_code = fields.Char(string='Mã Đề Quét Được (Mục 8)')
    exam_code = fields.Char(
        string='Mã Đề',
        compute='_compute_exam_code',
        store=True,
        help='Mã đề thi của bài kiểm tra'
    )

    @api.depends('exam_id.code', 'detected_exam_code')
    def _compute_exam_code(self):
        for record in self:
            record.exam_code = record.detected_exam_code or record.exam_id.code or ''

    scan_status = fields.Selection([
        ('none', 'Chưa Quét'),
        ('success', 'Đã Quét & Chấm Thành Công'),
        ('failed', 'Lỗi Nhận Diện / Sai Mã Đề')
    ], default='none', string='Trạng Thái Quét')
    scan_engine = fields.Selection([
        ('gemini_ai', 'Google Gemini AI (Có mạng)'),
        ('python_omr', 'Bộ Máy Python OMR (100% Offline)'),
        ('claude_vision', 'Claude Vision AI'),
    ], string='Bộ Máy Quét', default='python_omr')
    scan_mode = fields.Selection([
        ('auto', 'Tự Động (Gemini AI nếu có mạng, dự phòng Python Offline)'),
        ('gemini', 'Google Gemini AI (Yêu cầu mạng)'),
        ('python', 'Python OMR (100% Offline không cần mạng)'),
    ], default='auto', string='Chế Độ Quét')

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
        string='Tổng Số Đúng',
        compute='_compute_scores',
        store=True
    )
    wrong_count = fields.Integer(
        string='Tổng Số Sai',
        compute='_compute_scores',
        store=True
    )
    percentage = fields.Float(
        string='Tỷ Lệ (%)',
        compute='_compute_scores',
        store=True
    )
    correct_ratio = fields.Char(
        string='Số Câu Đúng',
        compute='_compute_scores',
        store=True
    )
    passed = fields.Boolean(
        string='Kết Quả Đạt',
        compute='_compute_passed',
        store=True
    )
    result_display = fields.Char(
        string='Kết Quả',
        compute='_compute_passed',
        store=True
    )

    answer_ids = fields.One2many('exam.answer', 'session_id', string='Chi Tiết Từng Câu Trả Lời')
    analysis_ids = fields.One2many('ai.analysis', 'session_id', string='Nhận Xét AI')

    @api.constrains('sbd')
    def _check_sbd_six_digits(self):
        for record in self:
            if record.sbd:
                clean = str(record.sbd).strip()
                if not re.match(r'^\d{6}$', clean):
                    raise exceptions.ValidationError(
                        f"Số báo danh '{record.sbd}' không hợp lệ! Số báo danh bắt buộc phải gồm đúng 6 chữ số (0-9) tương ứng với 6 cột ở mục 7 trên Phiếu trả lời trắc nghiệm OMR."
                    )

    @api.constrains('exam_id')
    def _check_exam_status(self):
        for record in self:
            if record.exam_id and record.exam_id.status != 'active':
                raise exceptions.ValidationError(
                    f"Đề thi '{record.exam_id.name}' đã đóng hoặc chưa được kích hoạt!"
                )

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id and self.student_id.class_id and not self.class_id:
            self.class_id = self.student_id.class_id

    @api.onchange('exam_id')
    def _onchange_exam_id(self):
        self.answer_ids = [Command.clear()]
        if self.exam_id:
            self.answer_ids = [
                Command.create({'question_id': question.id, 'answer_given': ''})
                for question in self.exam_id.question_ids
            ]

    @api.model_create_multi
    def create(self, vals_list):
        for idx, vals in enumerate(vals_list, start=1):
            student = self.env['school.student'].browse(vals['student_id']) if vals.get('student_id') else self.env['school.student']
            if not vals.get('class_id'):
                if vals.get('batch_id'):
                    batch = self.env['exam.batch'].browse(vals['batch_id'])
                    if batch.class_id:
                        vals['class_id'] = batch.class_id.id
                elif student and student.class_id:
                    vals['class_id'] = student.class_id.id

            # Tự động sinh Số Báo Danh 6 chữ số nếu chưa có
            if not vals.get('sbd'):
                used_sbds = set()
                if vals.get('batch_id'):
                    existing_sbds = self.search([('batch_id', '=', vals['batch_id'])]).mapped('sbd')
                    used_sbds.update(s for s in existing_sbds if s)
                vals['sbd'] = ExamBatch._format_six_digit_sbd(student.code if student else '', idx, used_sbds)

            if vals.get('exam_id') and not vals.get('answer_ids'):
                exam = self.env['exam.exam'].browse(vals['exam_id'])
                vals['answer_ids'] = [
                    Command.create({'question_id': q.id, 'answer_given': ''})
                    for q in exam.question_ids
                ]
        return super().create(vals_list)

    @api.depends('student_id.name', 'exam_id.name', 'sbd')
    def _compute_name(self):
        for record in self:
            sbd_prefix = f"[SBD: {record.sbd}] " if record.sbd else ""
            record.name = f"{sbd_prefix}{record.student_id.name or ''} - {record.exam_id.name or ''}"

    @api.depends('status', 'answer_ids.points_earned', 'answer_ids.is_correct', 'total_possible', 'answer_ids')
    def _compute_scores(self):
        for record in self:
            answers = record.answer_ids
            total_q = len(answers)
            if record.status != 'Graded':
                record.total_score = 0.0
                record.correct_count = 0
                record.wrong_count = 0
                record.percentage = 0.0
                record.correct_ratio = 'Không làm bài'
                continue

            correct_answers = answers.filtered(lambda a: a.is_correct)
            record.correct_count = len(correct_answers)
            record.wrong_count = total_q - record.correct_count
            record.correct_ratio = f"{record.correct_count}/{total_q} câu"

            if total_q > 0 and record.total_possible and record.total_possible > 0:
                point_per_q = record.total_possible / total_q
                record.total_score = round(record.correct_count * point_per_q, 2)
                record.percentage = round((record.correct_count / total_q) * 100.0, 1)
            else:
                record.total_score = round(sum(ans.points_earned for ans in answers), 2)
                if record.total_possible and record.total_possible > 0:
                    record.percentage = round((record.total_score / record.total_possible) * 100.0, 1)
                else:
                    record.percentage = 0.0

    def action_submit_exam(self, run_ai_online=False):
        """Chấm điểm bài thi học sinh và khởi tạo bản ghi phân tích AI"""
        self.ensure_one()
        self.status = 'Graded'
        if not self.end_time:
            self.end_time = fields.Datetime.now()

        for answer in self.answer_ids:
            answer._compute_evaluation()
        self._compute_scores()

        analysis = self.env['ai.analysis'].search([('session_id', '=', self.id)], limit=1)
        if not analysis:
            analysis = self.env['ai.analysis'].create({
                'session_id': self.id,
                'student_id': self.student_id.id,
                'status': 'pending',
            })

        # Nếu chấm hàng loạt qua file RAR, tạo sẵn nhận xét hoặc để Cron xử lý nhằm không gây treo HTTP Worker
        if self.auto_analyze and run_ai_online:
            try:
                analysis.action_analyze_with_gemini()
            except Exception as e:
                _logger.warning(f"Không thể tự động phân tích AI cho phiên {self.id}: {str(e)}")

    @api.depends('total_score', 'status')
    def _compute_passed(self):
        for record in self:
            if record.status == 'Graded':
                record.passed = (record.total_score >= 5.0)
                record.result_display = 'Đạt' if record.passed else 'Chưa Đạt (Rớt)'
            else:
                record.passed = False
                record.result_display = 'Không làm bài'

    def action_delete_session(self):
        """Xóa bài kiểm tra này của học sinh và làm mới điểm số"""
        self.ensure_one()
        student = self.student_id
        batch = self.batch_id
        self.unlink()
        if student.exists():
            student._compute_student_exam_stats()
        if batch.exists():
            batch._compute_batch_stats()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã xóa bài kiểm tra',
                'message': 'Đã xóa bài kiểm tra thành công. Điểm số của học sinh đã được làm mới.',
                'type': 'success',
                'sticky': False,
            }
        }

    def unlink(self):
        # Lấy danh sách học sinh và đợt thi trước khi xóa
        students = self.mapped('student_id')
        batches = self.mapped('batch_id')
        self.mapped('analysis_ids').unlink()
        self.mapped('answer_ids').unlink()
        res = super().unlink()
        # Điểm của học sinh khi bài kiểm tra đó bị xóa sẽ bị xóa theo không lưu lại kết quả
        if students.exists():
            students._compute_student_exam_stats()
        if batches.exists():
            batches._compute_batch_stats()
        return res

    def action_view_session_detail(self):
        """Mở chi tiết bài thi của học sinh để xem kết quả từng câu và ảnh phiếu OMR"""
        self.ensure_one()
        return {
            'name': f"Chi Tiết Bài Kiểm Tra - [SBD: {self.sbd or ''}] {self.student_name}",
            'type': 'ir.actions.act_window',
            'res_model': 'exam.session',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_session_answer_sheet(self):
        """Tải về phiếu trả lời trắc nghiệm PDF đã điền sẵn SBD 6 số của học sinh này"""
        self.ensure_one()
        batch_id = self.batch_id.id if self.batch_id else 0
        return {
            'type': 'ir.actions.act_url',
            'url': f"/educational_system/download_answer_sheet/{batch_id}?session_id={self.id}&mode=prefilled",
            'target': 'self',
        }


class ExamAnswer(models.Model):
    _name = 'exam.answer'
    _description = 'Chi Tiết Đáp Án'

    _sql_constraints = [
        ('unique_session_question', 'UNIQUE(session_id, question_id)', 'Một câu hỏi chỉ được trả lời 1 lần trong một lượt làm bài!'),
    ]

    session_id = fields.Many2one('exam.session', string='Phiên Thi', required=True, ondelete='cascade')
    question_id = fields.Many2one('exam.question', string='Câu Hỏi', required=True, ondelete='cascade')

    question_content = fields.Text(string='Đề Bài', related='question_id.content', readonly=True)
    question_type = fields.Selection(string='Dạng Câu Hỏi', related='question_id.question_type', readonly=True)
    option_a = fields.Char(string='Phương Án A', related='question_id.option_a', readonly=True)
    option_b = fields.Char(string='Phương Án B', related='question_id.option_b', readonly=True)
    option_c = fields.Char(string='Phương Án C', related='question_id.option_c', readonly=True)
    option_d = fields.Char(string='Phương Án D', related='question_id.option_d', readonly=True)
    correct_answer = fields.Selection(string='Đáp Án Đúng', related='question_id.correct_answer', readonly=True)
    explanation = fields.Text(string='Hướng Dẫn Giải', related='question_id.explanation', readonly=True)
    question_points = fields.Float(
        string='Thang Điểm',
        compute='_compute_question_points',
        store=True
    )

    answer_given = fields.Char(string='Đáp Án Của Học Sinh')
    is_correct = fields.Boolean(string='Đúng/Sai', compute='_compute_evaluation', store=True)
    result_text = fields.Char(string='Đánh Giá', compute='_compute_evaluation', store=True)
    points_earned = fields.Float(string='Điểm Nhận Được', compute='_compute_evaluation', store=True)

    @api.depends('session_id.total_possible', 'session_id.answer_ids')
    def _compute_question_points(self):
        for record in self:
            sess = record.session_id
            total_possible = sess.total_possible if sess and sess.total_possible else 10.0
            total_q = len(sess.answer_ids) if sess else 0
            if total_q > 0:
                record.question_points = round(total_possible / total_q, 2)
            elif record.question_id and record.question_id.points:
                record.question_points = record.question_id.points
            else:
                record.question_points = 1.0

    @api.constrains('question_id', 'session_id')
    def _check_question_belongs_to_exam(self):
        for record in self:
            if record.session_id and record.question_id and record.session_id.exam_id:
                if record.question_id not in record.session_id.exam_id.question_ids:
                    raise exceptions.ValidationError(
                        f"Lỗi: Câu hỏi '{record.question_id.code}' không thuộc Đề thi '{record.session_id.exam_id.name}'!"
                    )

    @staticmethod
    def _normalize_choice(val):
        if not val:
            return ""
        s = str(val).strip()
        m = re.search(r'\b([A-Da-d])\b', s)
        if m:
            return m.group(1).upper()
        s_upper = s.upper()
        for ch in ['A', 'B', 'C', 'D']:
            if s_upper.startswith(ch) or s_upper == ch:
                return ch
        return s_upper

    @api.depends('answer_given', 'question_id.correct_answer', 'question_points', 'session_id.status')
    def _compute_evaluation(self):
        for record in self:
            if not record.session_id or record.session_id.status != 'Graded':
                record.is_correct = False
                record.points_earned = 0.0
                record.result_text = 'Chưa Chấm'
                continue

            q = record.question_id
            if not record.answer_given or not q or not q.correct_answer:
                record.is_correct = False
                record.points_earned = 0.0
                record.result_text = 'Bỏ Trống'
                continue

            s_choice = self._normalize_choice(record.answer_given)
            c_choice = self._normalize_choice(q.correct_answer)
            pts = record.question_points if record.question_points > 0 else (q.points or 1.0)

            if s_choice and c_choice and s_choice == c_choice:
                record.is_correct = True
                record.points_earned = pts
                record.result_text = 'Đúng'
            else:
                record.is_correct = False
                record.points_earned = 0.0
                record.result_text = 'Sai'


class ExamAssignWizard(models.TransientModel):
    _name = 'exam.assign.wizard'
    _description = 'Wizard Tạo Đợt Kiểm Tra & Cấp SBD Cho Lớp'

    exam_id = fields.Many2one('exam.exam', string='Đề Thi Cần Giao', required=True, readonly=True)
    grade_id = fields.Many2one('school.grade', related='exam_id.grade_id', string='Khối Lớp', readonly=True)
    assign_type = fields.Selection([
        ('class', 'Giao Cho Toàn Bộ Lớp Học (Tạo Đợt Kiểm Tra & Cấp SBD 6 Số)'),
        ('students', 'Chọn Từng Học Sinh'),
    ], string='Hình Thức Giao Đề', default='class', required=True)
    class_id = fields.Many2one(
        'school.class',
        string='Lớp Học',
        domain="[('grade_id', 'in', [grade_id, False])]"
    )
    student_ids = fields.Many2many('school.student', string='Danh Sách Học Sinh')

    @api.constrains('exam_id')
    def _check_exam_active(self):
        for wizard in self:
            if wizard.exam_id and wizard.exam_id.status != 'active':
                raise exceptions.ValidationError("Đề thi này đã đóng hoặc chưa kích hoạt, không thể phát đề!")

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.class_id:
            return {'domain': {'student_ids': [('class_id', '=', self.class_id.id)]}}

    def action_assign_exam(self):
        """Tạo đợt kiểm tra mới cho lớp và tự động gán Số Báo Danh 6 chữ số cho từng học sinh"""
        self.ensure_one()
        if not self.class_id:
            raise exceptions.UserError("Vui lòng chọn lớp học để tạo đợt kiểm tra và cấp Số Báo Danh!")

        batch_code = f"KT-{self.class_id.code}-{fields.Datetime.now().strftime('%Y%m%d%H%M')}"
        batch = self.env['exam.batch'].create({
            'code': batch_code,
            'name': f"{self.exam_id.name} - {self.class_id.name}",
            'class_id': self.class_id.id,
            'exam_id': self.exam_id.id,
            'batch_type': 'regular',
            'status': 'in_progress',
        })
        return {
            'name': f'Đợt Kiểm Tra: {batch.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ExamQuestionImportWizard(models.TransientModel):
    _name = 'exam.question.import.wizard'
    _description = 'Wizard Import Ngân Hàng Câu Hỏi Từ Excel'

    @api.model
    def _default_grade_id(self):
        grade = self.env['school.grade'].search([('code', '=', 'KHOI_3')], limit=1)
        if not grade:
            grade = self.env['school.grade'].search([('status', '=', 'active')], limit=1)
        return grade.id if grade else False

    grade_id = fields.Many2one('school.grade', string='Khối Lớp Áp Dụng (*)', default=_default_grade_id, required=True)
    excel_file = fields.Binary(string='Tệp Excel (.xlsx)', required=False)
    filename = fields.Char(string='Tên Tệp')
    duplicate_behavior = fields.Selection([
        ('update', 'Cập nhật nội dung câu hỏi nếu mã đã tồn tại (Khuyên dùng)'),
        ('skip', 'Bỏ qua dòng trùng mã (giữ nguyên câu hỏi cũ)'),
        ('error', 'Báo lỗi và dừng import khi phát hiện trùng mã'),
    ], string='Quy Tắc Xử Lý Trùng Mã', default='update', required=True)
    default_points = fields.Float(string='Điểm Mặc Định Nếu Trống', default=1.0, required=True)
    state = fields.Selection([
        ('draft', 'Chọn Tệp'),
        ('done', 'Hoàn Tất'),
    ], default='draft')
    result_html = fields.Html(string='Kết Quả Import', readonly=True)

    def action_download_template(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/educational_system/download_question_template',
            'target': 'self',
        }

    def action_import_excel(self):
        """Đọc tệp Excel và import câu hỏi theo lô (Batch Insert, loại bỏ N+1 query)"""
        self.ensure_one()
        if not self.excel_file:
            raise exceptions.UserError("Vui lòng chọn tệp Excel (.xlsx) để tải lên!")

        if self.filename and not (self.filename.lower().endswith('.xlsx') or self.filename.lower().endswith('.xls')):
            raise exceptions.UserError("Định dạng tệp không hợp lệ! Vui lòng chỉ chọn tệp Excel có đuôi .xlsx hoặc .xls.")

        try:
            file_data = base64.b64decode(self.excel_file)
            wb = openpyxl.load_workbook(io.BytesIO(file_data), data_only=True)
        except Exception as e:
            raise exceptions.UserError(f"Không thể đọc file Excel. Chi tiết: {str(e)}")

        sheet = wb.active
        if not sheet or sheet.max_row < 2:
            raise exceptions.UserError("File Excel rỗng hoặc không chứa dòng dữ liệu nào sau dòng tiêu đề!")

        header_aliases = {
            'code': ['mã câu hỏi', 'mã ch', 'mã', 'code', 'ma cau hoi', 'mach'],
            'content': ['nội dung câu hỏi', 'nội dung', 'đề bài', 'câu hỏi', 'content', 'noi dung'],
            'topic': ['chủ đề', 'dạng toán', 'dạng bài', 'chủ đề toán', 'topic', 'chu de', 'dang toan'],
            'option_a': ['phương án a', 'đáp án a', 'lựa chọn a', 'a', 'option_a', 'phuong an a', 'dap an a', 'pa a'],
            'option_b': ['phương án b', 'đáp án b', 'lựa chọn b', 'b', 'option_b', 'phuong an b', 'dap an b', 'pa b'],
            'option_c': ['phương án c', 'đáp án c', 'lựa chọn c', 'c', 'option_c', 'phuong an c', 'dap an c', 'pa c'],
            'option_d': ['phương án d', 'đáp án d', 'lựa chọn d', 'd', 'option_d', 'phuong an d', 'dap an d', 'pa d'],
            'correct_answer': ['đáp án đúng', 'đáp án chuẩn', 'đáp án', 'correct_answer', 'dap an dung', 'dap an chuan', 'đáp án đúng (a/b/c/d)'],
            'difficulty': ['độ khó', 'mức độ', 'difficulty', 'do kho', 'muc do'],
            'points': ['điểm', 'thang điểm', 'points', 'diem'],
            'explanation': ['hướng dẫn giải', 'lời giải', 'giải thích', 'lời giải chi tiết', 'explanation', 'huong dan giai', 'loi giai'],
        }

        col_mapping = {}
        header_row = [sheet.cell(row=1, column=col).value for col in range(1, sheet.max_column + 1)]

        for col_idx, raw_val in enumerate(header_row, start=1):
            if not raw_val:
                continue
            clean_hdr = str(raw_val).strip().lower().replace('(*)', '').strip()
            for field_name, aliases in header_aliases.items():
                if any(alias in clean_hdr for alias in aliases):
                    if field_name not in col_mapping:
                        col_mapping[field_name] = col_idx
                    break

        required_cols = ['code', 'content', 'topic', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer']
        missing_required = [col for col in required_cols if col not in col_mapping]
        if missing_required:
            col_names_vi = {
                'code': 'Mã Câu Hỏi',
                'content': 'Nội Dung Câu Hỏi',
                'topic': 'Chủ Đề',
                'option_a': 'Phương Án A',
                'option_b': 'Phương Án B',
                'option_c': 'Phương Án C',
                'option_d': 'Phương Án D',
                'correct_answer': 'Đáp Án Đúng (A/B/C/D)',
            }
            missing_vi = [col_names_vi.get(c, c) for c in missing_required]
            raise exceptions.UserError(
                f"File Excel thiếu các cột bắt buộc: {', '.join(missing_vi)}."
            )

        total_rows = 0
        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []
        seen_codes_in_file = set()
        parsed_rows = []

        for row_idx in range(2, sheet.max_row + 1):
            row_data = {}
            has_any_value = False
            for field_name, col_idx in col_mapping.items():
                val = sheet.cell(row=row_idx, column=col_idx).value
                if val is not None and str(val).strip() != '':
                    has_any_value = True
                    row_data[field_name] = str(val).strip()
                else:
                    row_data[field_name] = ''

            if not has_any_value:
                continue

            total_rows += 1
            code = row_data.get('code', '').strip().upper()
            if not code:
                errors.append(f"Dòng {row_idx}: Thiếu Mã Câu Hỏi.")
                continue

            if code in seen_codes_in_file:
                errors.append(f"Dòng {row_idx}: Trùng mã '{code}' ngay trong tệp Excel.")
                continue
            seen_codes_in_file.add(code)

            content = row_data.get('content', '').strip()
            if not content:
                errors.append(f"Dòng {row_idx}: Thiếu Nội Dung Câu Hỏi (Mã: {code}).")
                continue

            option_a = row_data.get('option_a', '').strip()
            option_b = row_data.get('option_b', '').strip()
            option_c = row_data.get('option_c', '').strip()
            option_d = row_data.get('option_d', '').strip()

            if not (option_a and option_b and option_c and option_d):
                errors.append(f"Dòng {row_idx}: Câu hỏi '{code}' cần điền đủ 4 phương án A, B, C, D.")
                continue

            raw_correct = row_data.get('correct_answer', '').strip().upper()
            correct_norm = next((ch for ch in ['A', 'B', 'C', 'D'] if raw_correct == ch or raw_correct.startswith(ch)), None)
            if not correct_norm:
                errors.append(f"Dòng {row_idx}: Đáp án đúng '{raw_correct}' không hợp lệ (Mã: {code}).")
                continue

            topic_raw = row_data.get('topic', '').strip().lower()
            topic = None
            if any(k in topic_raw for k in ['cộng', 'addition', 'cong']):
                topic = 'Addition'
            elif any(k in topic_raw for k in ['trừ', 'subtraction', 'tru']):
                topic = 'Subtraction'
            elif any(k in topic_raw for k in ['nhân', 'multiplication', 'nhan']):
                topic = 'Multiplication'
            elif any(k in topic_raw for k in ['chia', 'division']):
                topic = 'Division'
            elif any(k in topic_raw for k in ['hình', 'geometry', 'hinh']):
                topic = 'Geometry'
            elif any(k in topic_raw for k in ['lời văn', 'văn', 'word', 'loi van']):
                topic = 'WordProblem'

            if not topic:
                errors.append(f"Dòng {row_idx}: Chủ đề '{row_data.get('topic')}' không hợp lệ.")
                continue

            diff_raw = row_data.get('difficulty', '').strip().lower()
            if any(k in diff_raw for k in ['dễ', 'easy', 'de']):
                difficulty = 'Easy'
            elif any(k in diff_raw for k in ['khó', 'hard', 'kho']):
                difficulty = 'Hard'
            else:
                difficulty = 'Medium'

            try:
                points_val = float(row_data.get('points')) if row_data.get('points') else self.default_points
                points = points_val if points_val > 0 else 1.0
            except Exception:
                points = self.default_points if self.default_points > 0 else 1.0

            explanation = row_data.get('explanation', '').strip()
            vals = {
                'code': code,
                'grade_id': self.grade_id.id,
                'content': content,
                'topic': topic,
                'question_type': 'single_choice',
                'option_a': option_a,
                'option_b': option_b,
                'option_c': option_c,
                'option_d': option_d,
                'correct_answer': correct_norm,
                'difficulty': difficulty,
                'points': points,
                'explanation': explanation or False,
            }
            parsed_rows.append((row_idx, code, vals))

        # Batch fetch 1 lần để tránh N+1 query
        all_codes = [r[1] for r in parsed_rows]
        existing_map = {
            q.code: q for q in self.env['exam.question'].search([('code', 'in', all_codes)])
        } if all_codes else {}

        to_create = []
        for row_idx, code, vals in parsed_rows:
            existing = existing_map.get(code)
            if existing:
                if self.duplicate_behavior == 'error':
                    raise exceptions.UserError(f"Phát hiện trùng mã câu hỏi '{code}' tại dòng {row_idx}!")
                elif self.duplicate_behavior == 'skip':
                    skipped_count += 1
                elif self.duplicate_behavior == 'update':
                    existing.write(vals)
                    updated_count += 1
            else:
                to_create.append(vals)
                created_count += 1

        if to_create:
            self.env['exam.question'].create(to_create)

        err_html = ""
        if errors:
            err_items = "".join([f"<li class='text-danger mb-1'>{html.escape(err)}</li>" for err in errors])
            err_html = f"""
            <div class="alert alert-danger mt-3" role="alert">
                <h6 class="alert-heading fw-bold mb-2"><i class="fa fa-exclamation-triangle me-1"/> Các Dòng Bị Lỗi ({len(errors)} dòng):</h6>
                <ul class="mb-0 ps-3">{err_items}</ul>
            </div>
            """

        result_html = f"""
        <div class="p-2">
            <div class="alert alert-success" role="status">
                <h5 class="alert-heading fw-bold mb-3"><i class="fa fa-check-circle me-1"/> Kết Quả Import Câu Hỏi ({html.escape(self.grade_id.name or '')}):</h5>
                <div class="row text-center g-2 mb-2">
                    <div class="col-3"><div class="p-2 border rounded bg-white"><small class="text-muted d-block">Tổng số dòng</small><span class="fs-4 fw-bold text-dark">{total_rows}</span></div></div>
                    <div class="col-3"><div class="p-2 border rounded bg-white"><small class="text-muted d-block">Tạo mới</small><span class="fs-4 fw-bold text-success">{created_count}</span></div></div>
                    <div class="col-3"><div class="p-2 border rounded bg-white"><small class="text-muted d-block">Cập nhật</small><span class="fs-4 fw-bold text-primary">{updated_count}</span></div></div>
                    <div class="col-3"><div class="p-2 border rounded bg-white"><small class="text-muted d-block">Bỏ qua / Lỗi</small><span class="fs-4 fw-bold text-warning">{skipped_count + len(errors)}</span></div></div>
                </div>
            </div>
            {err_html}
        </div>
        """

        self.write({'state': 'done', 'result_html': result_html})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        self.write({'state': 'draft', 'excel_file': False, 'filename': False, 'result_html': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_questions(self):
        return self.env['ir.actions.act_window']._for_xml_id('educational_system.action_exam_question')


class ExamCodeErrorWizard(models.TransientModel):
    _name = 'exam.code.error.wizard'
    _description = 'Cửa Sổ Thông Báo Tô Sai Mã Đề'

    session_id = fields.Many2one('exam.session', string='Bài Thi', readonly=True)
    batch_id = fields.Many2one('exam.batch', string='Đợt Kiểm Tra', readonly=True)
    student_name = fields.Char(string='Họ Và Tên Thí Sinh', readonly=True)
    student_code = fields.Char(string='Mã Sinh Viên', readonly=True)
    class_name = fields.Char(string='Lớp Học', readonly=True)
    exam_name = fields.Char(string='Tên Đề Thi', readonly=True)

    expected_exam_code = fields.Char(string='Mã Đề Được Gán', readonly=True)
    detected_exam_code = fields.Char(string='Mã Đề Nhận Diện', readonly=True)
    error_reason = fields.Text(string='Lý Do Cảnh Báo', readonly=True)


class ExamSessionScanWizard(models.TransientModel):
    _name = 'exam.session.scan.wizard'
    _description = 'Wizard Xem Ảnh Quét Bài Thi'

    session_id = fields.Many2one('exam.session', string='Bài Thi Học Sinh', required=True)
    student_id = fields.Many2one('school.student', related='session_id.student_id', string='Học Sinh', readonly=True)
    student_code = fields.Char(related='session_id.student_code', string='Mã HS', readonly=True)
    exam_id = fields.Many2one('exam.exam', related='session_id.exam_id', string='Đề Thi', readonly=True)
    scan_mode = fields.Selection([
        ('auto', 'Tự Động'),
        ('gemini', 'Google Gemini AI (Online)'),
        ('python', 'Python OMR (Offline)'),
    ], string='Chế Độ Quét', default='auto', required=True)
    scanned_image = fields.Binary(string='Ảnh Phiếu Trắc Nghiệm')
    filename = fields.Char(string='Tên Tệp Ảnh')
    state = fields.Selection([('draft', 'Chọn Ảnh'), ('done', 'Kết Quả')], default='draft')
    result_html = fields.Html(string='Báo Cáo Kết Quả')


class ExamBatchScanWizard(models.TransientModel):
    _name = 'exam.batch.scan.wizard'
    _description = 'Wizard Chấm Bài Kiểm Tra Hàng Loạt Bằng File Nén RAR / ZIP'

    batch_id = fields.Many2one('exam.batch', string='Đợt Kiểm Tra', required=True, readonly=True)
    class_id = fields.Many2one('school.class', related='batch_id.class_id', string='Lớp Học', readonly=True)
    exam_id = fields.Many2one('exam.exam', related='batch_id.exam_id', string='Đề Thi Áp Dụng', readonly=True)
    expected_exam_code = fields.Char(related='batch_id.exam_id.code', string='Mã Đề Chuẩn (6 số)', readonly=True)
    archive_file = fields.Binary(
        string='Tệp Nén Bài Thi (.RAR / .ZIP) (*)',
        required=False,
        help='Nén toàn bộ hình ảnh phiếu trả lời trắc nghiệm của học sinh trong lớp vào 1 file .RAR (hoặc .ZIP) và tải lên đây'
    )
    filename = fields.Char(string='Tên Tệp Nén')
    state = fields.Selection([
        ('draft', 'Tải File Nén RAR'),
        ('done', 'Báo Cáo Kết Quả Chấm Hàng Loạt'),
    ], default='draft')
    scan_mode = fields.Selection([
        ('auto', 'Tự Động (Gemini AI nếu có mạng, dự phòng Python OMR Offline)'),
        ('gemini', 'Google Gemini AI (Yêu cầu mạng)'),
        ('python', 'Python OMR (100% Offline - Tốc độ cao)'),
    ], default='python', string='Bộ Máy Nhận Diện OMR', required=True)
    result_html = fields.Html(string='Báo Cáo Kết Quả Chấm Hàng Loạt')

    def action_download_sample_rar(self):
        """Tải về ngay 1 file .RAR mẫu chứa ảnh bài làm của toàn bộ học sinh trong đợt kiểm tra này để test"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/educational_system/download_batch_sample_rar/{self.batch_id.id}",
            'target': 'self',
        }

    def action_reset(self):
        """Đặt lại wizard để giáo viên có thể upload tệp khác"""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'archive_file': False,
            'filename': False,
            'result_html': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'exam.batch.scan.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_scan_and_grade(self):
        """
        Giải nén tệp .RAR / .ZIP chứa toàn bộ hình ảnh bài thi của lớp và phân tích tự động từng ảnh:
        1. Quét Số Báo Danh (6 chữ số ở mục 7 đã được tô đen) -> Gán cho đúng học sinh có SBD đó trong đợt thi.
        2. Quét Mã Đề Thi (6 chữ số ở mục 8 đã được tô đen) -> Đối chiếu với mã đề thi của đợt kiểm tra.
        3. Quét 50 câu trả lời trắc nghiệm đã được tô đen -> Chấm điểm và gắn kết quả vào hồ sơ Học sinh.
        """
        self.ensure_one()
        if not self.archive_file:
            raise exceptions.UserError(
                "Vui lòng chọn tệp nén (.rar hoặc .zip) chứa toàn bộ hình ảnh bài thi của học sinh để tải lên!"
            )

        batch = self.batch_id
        if batch.status != 'in_progress':
            raise exceptions.UserError(
                "Chức năng chấm bài hàng loạt qua file RAR chỉ khả dụng khi đợt kiểm tra ở trạng thái 'Đang Diễn Ra'!"
            )

        # Đảm bảo danh sách học sinh của đợt thi đã được cấp SBD 6 số đầy đủ
        if not batch.session_ids:
            batch._auto_populate_students_with_sbd()
        else:
            used_sbds = set(s.sbd for s in batch.session_ids if s.sbd)
            for idx, sess in enumerate(batch.session_ids, start=1):
                if not sess.sbd:
                    sess.sbd = batch._format_six_digit_sbd(sess.student_id.code, idx, used_sbds)

        raw_archive = base64.b64decode(self.archive_file)
        try:
            extracted_images = omr_engine.extract_images_from_archive(raw_archive, self.filename or 'bai_thi.rar')
        except Exception as e:
            raise exceptions.UserError(str(e))

        if not extracted_images:
            raise exceptions.UserError(
                "Không tìm thấy tệp hình ảnh nào (.jpg, .jpeg, .png, .bmp, .webp) bên trong tệp nén đã tải lên!"
            )

        exam = batch.exam_id
        expected_code = (exam.code or '102345').strip()
        total_q = len(exam.question_ids)
        if total_q == 0:
            raise exceptions.UserError(f"Đề thi '{exam.name}' chưa có câu hỏi nào để chấm điểm!")

        gemini_key = self.env['ir.config_parameter'].sudo().get_param('ai.gemini_api_key') or os.environ.get('GEMINI_API_KEY')

        # Xây dựng bảng tra cứu nhanh học sinh trong đợt kiểm tra theo Số Báo Danh 6 chữ số
        session_by_sbd = {}
        for sess in batch.session_ids:
            if sess.sbd:
                clean_key = re.sub(r'\D', '', sess.sbd).zfill(6)[-6:]
                session_by_sbd[clean_key] = sess
                session_by_sbd[sess.sbd.strip()] = sess
            if sess.student_code:
                code_digits = re.sub(r'\D', '', sess.student_code)
                if code_digits:
                    norm_code = code_digits.zfill(6)[-6:]
                    session_by_sbd.setdefault(norm_code, sess)

        # ĐẶT LẠI TOÀN BỘ PHIÊN THI: Điểm số và kết quả luôn dựa trên lần quét cuối cùng, không chen lẫn giữa 2 lần
        batch.session_ids.write({
            'status': 'NotStarted',
            'scanned_image': False,
            'scanned_image_filename': False,
            'scan_date': False,
            'ocr_detected_answers': False,
            'detected_student_code': False,
            'detected_exam_code': False,
            'scan_status': 'none',
            'start_time': False,
            'end_time': False,
        })
        # Xóa phân tích AI cũ và làm trắng đáp án đã chọn trước đó
        batch.session_ids.mapped('analysis_ids').unlink()
        for ans in batch.session_ids.mapped('answer_ids'):
            ans.write({
                'answer_given': False,
                'points_earned': 0.0,
                'is_correct': False,
            })
        batch.session_ids._compute_scores()
        batch.session_ids._compute_passed()

        success_count = 0
        error_count = 0
        report_rows_html = ""
        graded_session_ids = set()

        for idx, (img_name, img_bytes) in enumerate(extracted_images, start=1):
            # 1. Quét SBD, Mã đề và các ô đáp án đã được tô đen
            hdr_sbd, hdr_exam_code = omr_engine.detect_header_codes(img_bytes)
            res = omr_engine.grade_sheet_from_image(
                img_bytes,
                total_questions=total_q,
                gemini_api_key=gemini_key,
                engine_preference=self.scan_mode or 'python',
                exam_code=expected_code
            )

            raw_sbd = (res.get('detected_student_code', '') or hdr_sbd or '').strip()
            sbd_digits = re.sub(r'\D', '', raw_sbd)
            norm_sbd = sbd_digits.zfill(6)[-6:] if sbd_digits else ''

            res_exam_code = (res.get('detected_exam_code', '') or hdr_exam_code or '').strip()
            detected_answers = res.get('detected_answers', {})
            engine_used = res.get('engine', 'python_omr')

            # 2. Tìm học sinh tương ứng với Số Báo Danh đã tô đen
            matched_session = None
            if norm_sbd:
                matched_session = session_by_sbd.get(norm_sbd) or session_by_sbd.get(raw_sbd)

            if not matched_session:
                error_count += 1
                report_rows_html += f"""
                <tr class="table-danger">
                    <td class="text-center fw-bold">{idx}</td>
                    <td class="font-monospace small">{html.escape(img_name)}</td>
                    <td class="text-center fw-bold text-danger">{html.escape(raw_sbd or 'Chưa tô / Trống')}</td>
                    <td class="text-danger fw-bold">Không tìm thấy HS khớp SBD</td>
                    <td class="text-center">{html.escape(res_exam_code or '-')}</td>
                    <td class="text-center">-</td>
                    <td class="text-center">-</td>
                    <td><span class="badge bg-danger">Lỗi SBD: Không khớp học sinh trong đợt thi</span></td>
                </tr>
                """
                continue

            # 3. Kiểm tra Mã Đề Thi đã tô đen có khớp với đề thi của đợt kiểm tra không
            if not omr_engine.check_exam_code_match(res_exam_code, expected_code):
                error_count += 1
                matched_session.write({
                    'scanned_image': base64.b64encode(img_bytes),
                    'scanned_image_filename': img_name,
                    'scan_date': fields.Datetime.now(),
                    'scan_engine': engine_used,
                    'detected_student_code': norm_sbd,
                    'detected_exam_code': res_exam_code,
                    'scan_status': 'failed',
                })
                report_rows_html += f"""
                <tr class="table-warning">
                    <td class="text-center fw-bold">{idx}</td>
                    <td class="font-monospace small">{html.escape(img_name)}</td>
                    <td class="text-center fw-bold text-primary">{html.escape(matched_session.sbd)}</td>
                    <td class="fw-bold">[{html.escape(matched_session.student_code)}] {html.escape(matched_session.student_name)}</td>
                    <td class="text-center fw-bold text-danger">{html.escape(res_exam_code or 'Trống')} ≠ {html.escape(expected_code)}</td>
                    <td class="text-center">-</td>
                    <td class="text-center">-</td>
                    <td><span class="badge bg-danger">Tô sai mã đề (Yêu cầu: {html.escape(expected_code)})</span></td>
                </tr>
                """
                continue

            # 4. Cập nhật đáp án cho từng câu hỏi và tính điểm cho học sinh
            if not matched_session.answer_ids or matched_session.exam_id.id != exam.id:
                matched_session.exam_id = exam.id
                matched_session.answer_ids.unlink()
                matched_session.answer_ids = [
                    Command.create({'question_id': q.id, 'answer_given': ''})
                    for q in exam.question_ids
                ]

            sorted_answers = matched_session.answer_ids.sorted(key=lambda a: a.question_id.code or str(a.question_id.id))
            for q_idx, ans_line in enumerate(sorted_answers, start=1):
                chosen = detected_answers.get(str(q_idx), '').strip().upper()
                ans_line.write({'answer_given': chosen if chosen in ['A', 'B', 'C', 'D'] else ''})

            matched_session.write({
                'scanned_image': base64.b64encode(img_bytes),
                'scanned_image_filename': img_name,
                'scan_date': fields.Datetime.now(),
                'scan_engine': engine_used,
                'ocr_detected_answers': json.dumps(res, ensure_ascii=False, indent=2),
                'detected_student_code': norm_sbd,
                'detected_exam_code': res_exam_code,
                'scan_status': 'success',
            })

            matched_session.action_submit_exam(run_ai_online=False)
            graded_session_ids.add(matched_session.id)
            success_count += 1

            score_cls = "text-success" if matched_session.passed else "text-danger"
            badge_cls = "bg-success" if matched_session.passed else "bg-danger"
            report_rows_html += f"""
            <tr>
                <td class="text-center fw-bold">{idx}</td>
                <td class="font-monospace small">{html.escape(img_name)}</td>
                <td class="text-center fw-bold text-primary font-monospace">{html.escape(matched_session.sbd)}</td>
                <td class="fw-bold">[{html.escape(matched_session.student_code)}] {html.escape(matched_session.student_name)}</td>
                <td class="text-center font-monospace text-success fw-bold">{html.escape(res_exam_code)}</td>
                <td class="text-center fw-bold">{html.escape(matched_session.correct_ratio)}</td>
                <td class="text-center fw-bold fs-6 {score_cls}">{matched_session.total_score} / {matched_session.total_possible}</td>
                <td><span class="badge {badge_cls}">{html.escape(matched_session.result_display)}</span></td>
            </tr>
            """

        # Xử lý các học sinh không có bài thi trong lần quét này: hiển thị "Không làm bài"
        unscanned_sessions = batch.session_ids.filtered(lambda s: s.id not in graded_session_ids)
        for un_sess in unscanned_sessions:
            un_sess.write({
                'status': 'NotStarted',
                'scan_status': 'none',
            })
            un_sess._compute_scores()
            un_sess._compute_passed()

        # Thêm các học sinh không làm bài vào bảng báo cáo kết quả
        for un_sess in unscanned_sessions.sorted(key=lambda s: s.sbd or s.student_code or ''):
            report_rows_html += f"""
            <tr class="table-light text-muted">
                <td class="text-center fw-bold text-secondary">-</td>
                <td class="font-monospace small text-muted"><em>(Không có ảnh trong file RAR)</em></td>
                <td class="text-center fw-bold text-secondary font-monospace">{html.escape(un_sess.sbd or '-')}</td>
                <td class="text-muted">[{html.escape(un_sess.student_code or '')}] {html.escape(un_sess.student_name or '')}</td>
                <td class="text-center text-muted">-</td>
                <td class="text-center"><span class="badge bg-secondary">Không làm bài</span></td>
                <td class="text-center fw-bold text-muted">0.0 / {un_sess.total_possible}</td>
                <td><span class="badge bg-secondary">Không làm bài</span></td>
            </tr>
            """

        # Cập nhật thống kê bài thi của đợt và của học sinh ngay lập tức
        batch._compute_batch_stats()
        if batch.session_ids.mapped('student_id'):
            batch.session_ids.mapped('student_id')._compute_student_exam_stats()

        total_files = len(extracted_images)
        result_html = f"""
        <div class="p-2">
            <div class="alert {'alert-success' if error_count == 0 else 'alert-warning'} d-flex align-items-center justify-content-between p-3 mb-3">
                <div>
                    <h5 class="fw-bold mb-1">
                        <i class="fa fa-archive me-1"/> Hoàn Tất Giải Nén &amp; Chấm Bài Từ Tệp: {html.escape(self.filename or 'bai_thi.rar')}
                    </h5>
                    <p class="mb-0 small">
                        Đợt kiểm tra: <strong>{html.escape(batch.name)}</strong> | Lớp: <strong>{html.escape(batch.class_id.name)}</strong> | Mã đề chuẩn: <strong>{html.escape(expected_code)}</strong>
                    </p>
                </div>
            </div>

            <div class="row text-center g-2 mb-3">
                <div class="col-3">
                    <div class="p-2 border rounded bg-light">
                        <small class="text-muted d-block">Tổng Số Ảnh Trong File</small>
                        <span class="fs-4 fw-bold text-dark">{total_files} ảnh</span>
                    </div>
                </div>
                <div class="col-3">
                    <div class="p-2 border rounded bg-light">
                        <small class="text-muted d-block">Đã Chấm Thành Công</small>
                        <span class="fs-4 fw-bold text-success">{success_count} bài</span>
                    </div>
                </div>
                <div class="col-3">
                    <div class="p-2 border rounded bg-light">
                        <small class="text-muted d-block">Không Làm Bài</small>
                        <span class="fs-4 fw-bold text-secondary">{len(unscanned_sessions)} HS</span>
                    </div>
                </div>
                <div class="col-3">
                    <div class="p-2 border rounded bg-light">
                        <small class="text-muted d-block">Lỗi SBD / Sai Mã Đề</small>
                        <span class="fs-4 fw-bold {'text-danger' if error_count > 0 else 'text-muted'}">{error_count} bài</span>
                    </div>
                </div>
            </div>

            <div class="table-responsive border rounded bg-white mt-2" style="max-height: 360px; overflow-y: auto;">
                <table class="table table-sm table-bordered table-hover align-middle mb-0">
                    <thead class="table-primary sticky-top">
                        <tr>
                            <th class="text-center">#</th>
                            <th>Tệp Ảnh</th>
                            <th class="text-center">SBD Quét Được</th>
                            <th>Học Sinh Được Gán</th>
                            <th class="text-center">Mã Đề Quét Được</th>
                            <th class="text-center">Số Câu Đúng</th>
                            <th class="text-center">Điểm Số</th>
                            <th>Trạng Thái</th>
                        </tr>
                    </thead>
                    <tbody>
                        {report_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
        """

        self.write({
            'state': 'done',
            'result_html': result_html,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_scan_next(self):
        """Cho phép tải lên một tệp nén RAR/ZIP khác"""
        self.write({
            'state': 'draft',
            'archive_file': False,
            'filename': False,
            'result_html': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class ExamAddCalculationWizard(models.TransientModel):
    _name = 'exam.add.calculation.wizard'
    _description = 'Wizard Thêm Phép Tính Trực Tiếp Trên Odoo'

    @api.model
    def _default_grade_id(self):
        grade = self.env['school.grade'].search([('code', '=', 'KHOI_3')], limit=1)
        if not grade:
            grade = self.env['school.grade'].search([('status', '=', 'active')], limit=1)
        return grade.id if grade else False

    exam_id = fields.Many2one('exam.exam', string='Đề Thi Tiếp Nhận', required=False)
    grade_id = fields.Many2one('school.grade', string='Khối Lớp (*)', default=_default_grade_id, required=True)
    calc_mode = fields.Selection([
        ('two_nums', 'Phép Tính 2 Số (+, -, ×, ÷)'),
        ('find_x', 'Tìm Thành Phần Chưa Biết / Tìm x (vd: x + 15 = 40)'),
        ('custom', 'Biểu Thức Tùy Ý (vd: 125 + 45 - 20)'),
    ], string='Chế Độ Nhập Phép Tính', default='two_nums', required=True)

    num1 = fields.Integer(string='Số Thứ Nhất', default=15)
    operation = fields.Selection([
        ('+', 'Cộng (+)'),
        ('-', 'Trừ (-)'),
        ('*', 'Nhân (×)'),
        ('/', 'Chia (÷)'),
    ], string='Phép Tính', default='+')
    num2 = fields.Integer(string='Số Thứ Hai', default=7)

    custom_expression = fields.Char(string='Biểu Thức Tùy Ý')

    question_text = fields.Char(string='Nội Dung Đề Bài', required=True, default='Tính: 15 + 7 = ?')
    result_val = fields.Char(string='Kết Quả Đúng', default='22', readonly=True)

    option_a = fields.Char(string='Phương Án A', required=True, default='22')
    option_b = fields.Char(string='Phương Án B', required=True, default='21')
    option_c = fields.Char(string='Phương Án C', required=True, default='23')
    option_d = fields.Char(string='Phương Án D', required=True, default='32')
    correct_answer = fields.Selection([
        ('A', 'A'),
        ('B', 'B'),
        ('C', 'C'),
        ('D', 'D'),
    ], string='Đáp Án Đúng (*)', default='A', required=True)

    topic = fields.Selection([
        ('Addition', 'Phép Cộng'),
        ('Subtraction', 'Phép Trừ'),
        ('Multiplication', 'Phép Nhân'),
        ('Division', 'Phép Chia'),
        ('MixedOperation', 'Biểu Thức / Phép Tính Hỗn Hợp'),
        ('FindX', 'Tìm Thành Phần Chưa Biết (Tìm x)'),
        ('Geometry', 'Hình Học'),
        ('WordProblem', 'Toán Lời Văn'),
    ], string='Chủ Đề Toán', default='Addition', required=True)
    difficulty = fields.Selection([
        ('Easy', 'Dễ'),
        ('Medium', 'Trung Bình'),
        ('Hard', 'Khó'),
    ], string='Độ Khó', default='Medium', required=True)
    points = fields.Float(string='Điểm Câu Hỏi', default=1.0, required=True)

    @api.onchange('calc_mode', 'num1', 'operation', 'num2', 'custom_expression')
    def _onchange_calc_inputs(self):
        import random
        ans_num = None
        op_sign = '+'
        if self.calc_mode == 'two_nums':
            n1 = self.num1 or 0
            n2 = self.num2 or 0
            op = self.operation or '+'
            if op == '+':
                ans_num = n1 + n2
                op_sign = '+'
                self.topic = 'Addition'
            elif op == '-':
                ans_num = n1 - n2
                op_sign = '-'
                self.topic = 'Subtraction'
            elif op == '*':
                ans_num = n1 * n2
                op_sign = '×'
                self.topic = 'Multiplication'
            elif op == '/':
                if n2 == 0:
                    ans_num = 0
                else:
                    ans_num = n1 // n2 if n1 % n2 == 0 else round(n1 / n2, 2)
                op_sign = ':'
                self.topic = 'Division'
            self.question_text = f"Tính: {n1} {op_sign} {n2} = ?"
        elif self.calc_mode == 'find_x':
            n1 = self.num1 or 0
            n2 = self.num2 or 0
            op = self.operation or '+'
            self.topic = 'FindX'
            if op == '+':
                total = n1 + n2
                ans_num = n2
                self.question_text = f"Tìm x, biết: x + {n1} = {total}"
            elif op == '-':
                ans_num = n1 + n2
                self.question_text = f"Tìm x, biết: x - {n1} = {n2}"
            elif op == '*':
                total = n1 * n2
                ans_num = n2
                self.question_text = f"Tìm x, biết: x × {n1} = {total}"
            elif op == '/':
                ans_num = n1 * n2
                self.question_text = f"Tìm x, biết: x : {n1} = {n2}"
        else:
            expr = (self.custom_expression or '').strip()
            if expr:
                try:
                    ans_num = safe_eval_math_expression(expr)
                except Exception:
                    ans_num = 0
                self.question_text = f"Kết quả của biểu thức {expr} là:"
                self.topic = 'MixedOperation'

        if ans_num is not None:
            self.result_val = str(ans_num)
            distractors = set()
            d_candidates = [
                ans_num + 1, ans_num - 1, ans_num + 10, ans_num - 10,
                ans_num + 2, ans_num - 2, ans_num + 5, ans_num - 5
            ]
            for cand in d_candidates:
                if cand != ans_num and cand >= 0:
                    distractors.add(cand)
                if len(distractors) >= 3:
                    break
            while len(distractors) < 3:
                distractors.add(ans_num + len(distractors) + 3)
            distractor_list = list(distractors)[:3]

            positions = ['A', 'B', 'C', 'D']
            chosen_pos = random.choice(positions)
            self.correct_answer = chosen_pos

            opts = {}
            d_idx = 0
            for pos in positions:
                if pos == chosen_pos:
                    opts[pos] = str(ans_num)
                else:
                    opts[pos] = str(distractor_list[d_idx])
                    d_idx += 1

            self.option_a = opts['A']
            self.option_b = opts['B']
            self.option_c = opts['C']
            self.option_d = opts['D']

    def action_add_to_exam(self):
        self.ensure_one()
        question = self._create_question()
        target_name = f"đề thi '{self.exam_id.name}'" if self.exam_id else "ngân hàng câu hỏi"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f"Đã thêm câu hỏi '{question.content}' vào {target_name}!",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }

    def action_add_and_continue(self):
        self.ensure_one()
        self._create_question()
        import random
        new_n1 = random.randint(10, 99)
        new_n2 = random.randint(2, 50)
        ctx = {
            'default_grade_id': self.grade_id.id,
            'default_num1': new_n1,
            'default_num2': new_n2,
            'default_operation': self.operation,
            'default_calc_mode': self.calc_mode,
            'default_topic': self.topic,
        }
        title = 'Thêm Phép Tính Trực Tiếp Vào Ngân Hàng Câu Hỏi'
        if self.exam_id:
            ctx['default_exam_id'] = self.exam_id.id
            title = f'Thêm Phép Tính Trực Tiếp Vào Đề: {self.exam_id.name}'

        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'exam.add.calculation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def _create_question(self):
        self.ensure_one()
        import time, random
        code = f"CH-PT-{time.strftime('%y%m%d%H%M%S')}-{random.randint(10, 99)}"
        question = self.env['exam.question'].create({
            'code': code,
            'grade_id': self.grade_id.id,
            'content': self.question_text,
            'question_type': 'single_choice',
            'option_a': self.option_a,
            'option_b': self.option_b,
            'option_c': self.option_c,
            'option_d': self.option_d,
            'correct_answer': self.correct_answer,
            'topic': self.topic,
            'difficulty': self.difficulty,
            'points': self.points,
        })
        if self.exam_id:
            self.exam_id.write({'question_ids': [(4, question.id)]})
        return question


class ExamBatchFinishWizard(models.TransientModel):
    _name = 'exam.batch.finish.wizard'
    _description = 'Xác Nhận Hoàn Tất Đợt Kiểm Tra'

    batch_id = fields.Many2one('exam.batch', string='Đợt Kiểm Tra', required=True, readonly=True)
    total_count = fields.Integer(string='Tổng Số Học Sinh', compute='_compute_counts')
    graded_count = fields.Integer(string='Số HS Đã Chấm', compute='_compute_counts')
    ungraded_count = fields.Integer(string='Số HS Chưa Chấm', compute='_compute_counts')
    confirm_finished = fields.Boolean(string='Chắc chắn đã chấm xong', default=False)

    @api.depends('batch_id')
    def _compute_counts(self):
        for wiz in self:
            if wiz.batch_id:
                wiz.total_count = len(wiz.batch_id.session_ids)
                wiz.graded_count = len(wiz.batch_id.session_ids.filtered(lambda s: s.status == 'Graded'))
                wiz.ungraded_count = wiz.total_count - wiz.graded_count
            else:
                wiz.total_count = 0
                wiz.graded_count = 0
                wiz.ungraded_count = 0

    def action_confirm_finish(self):
        self.ensure_one()
        if not self.confirm_finished:
            raise exceptions.UserError("Vui lòng tích chọn 'Chắc chắn đã chấm xong' để xác nhận hoàn tất đợt kiểm tra!")
        self.batch_id.write({'status': 'completed'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Hoàn Tất Đợt Thi',
                'message': f"Đợt kiểm tra {self.batch_id.name} đã được chuyển sang trạng thái Hoàn Thành.",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'}
            }
        }
