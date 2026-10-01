# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions, Command
from datetime import timedelta
import re
import logging

_logger = logging.getLogger(__name__)

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
        ('QuickTest', 'Kiểm Tra Thường Xuyên (15 Phút)'),
        ('MidTerm', 'Kiểm Tra Giữa Kỳ'),
        ('FinalTerm', 'Kiểm Tra Cuối Kỳ')
    ], string='Loại Đề Thi', default='QuickTest', required=True)
    topic = fields.Char(string='Chủ Đề Kiến Thức', default='Tổng hợp Toán lớp 3')
    status = fields.Selection([
        ('draft', 'Dự Thảo'),
        ('active', 'Đang Hoạt Động'),
        ('closed', 'Đã Đóng')
    ], string='Trạng Thái', default='active', required=True)
    auto_analyze = fields.Boolean(
        string='Tự Động Phân Tích AI',
        default=True,
        help='Tự động kích hoạt phân tích Claude AI ngay sau khi học sinh nộp bài'
    )
    total_score = fields.Float(string='Tổng Điểm', default=10.0, required=True)
    time_limit_minutes = fields.Integer(string='Thời Gian (Phút)', default=15)
    question_ids = fields.Many2many(
        comodel_name='exam.question',
        relation='exam_exam_question_rel',
        column1='exam_id',
        column2='question_id',
        string='Ngân Hàng Câu Hỏi'
    )
    total_questions = fields.Integer(
        string='Tổng Số Câu Hỏi',
        compute='_compute_total_questions',
        store=True
    )
    session_ids = fields.One2many('exam.session', 'exam_id', string='Các Lượt Làm Bài')

    @api.depends('question_ids')
    def _compute_total_questions(self):
        for record in self:
            record.total_questions = len(record.question_ids)

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"

    def action_open_assign_wizard(self):
        """Mở cửa sổ Wizard để Giáo viên gán đề thi cho cả lớp hoặc nhiều học sinh"""
        self.ensure_one()
        if self.status != 'active':
            raise exceptions.UserError("Đề thi này đã đóng hoặc chưa kích hoạt, không thể gán đề cho học sinh!")
        return {
            'name': f'Gán Đề Thi: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_exam_id': self.id,
            }
        }


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
    question_type = fields.Selection([
        ('numeric', 'Số Học / Đo Lường (Điền Số/Kết Quả)'),
        ('single_choice', 'Trắc Nghiệm (A, B, C, D)'),
        ('text', 'Tự Luận Ngắn / Khái Niệm')
    ], string='Dạng Câu Hỏi', default='numeric', required=True)
    correct_answer = fields.Char(string='Đáp Án Chuẩn', required=True)
    acceptable_answers = fields.Char(
        string='Đáp Án Chấp Nhận Thêm',
        help='Các đáp án tương đương được chấp nhận, phân tách bởi dấu | hoặc ; (ví dụ: 15|15 quả|15 quả táo)'
    )
    tolerance = fields.Float(
        string='Dung Sai Số Học',
        default=0.0,
        help='Dung sai cho phép khi so sánh kết quả số học'
    )
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
    ], string='Độ Khó', default='Medium', required=True)
    explanation = fields.Text(string='Hướng Dẫn Giải / Lời Giải Chi Tiết')

    def _compute_display_name(self):
        for record in self:
            short_c = record.content[:40] if record.content else ''
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
    class_id = fields.Many2one(
        'school.class', 
        string='Lớp Học', 
        compute='_compute_class_id', 
        store=True, 
        readonly=False,
        ondelete='restrict'
    )
    start_time = fields.Datetime(string='Thời Gian Bắt Đầu')
    end_time = fields.Datetime(string='Thời Gian Nộp Bài')
    deadline = fields.Datetime(
        string='Hạn Chót Nộp Bài', 
        compute='_compute_deadline', 
        store=True,
        help='Thời điểm tối đa học sinh phải hoàn thành bài làm'
    )
    status = fields.Selection([
        ('NotStarted', 'Chưa Bắt Đầu'),
        ('InProgress', 'Đang Làm'),
        ('Submitted', 'Đã Nộp'),
        ('Graded', 'Đã Chấm'),
    ], default='NotStarted', string='Trạng Thái', required=True)
    auto_analyze = fields.Boolean(
        string='Tự Động Phân Tích AI',
        default=True,
        help='Tự động gửi sang mô hình AI phân tích ngay khi nộp bài'
    )

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
    wrong_count = fields.Integer(
        string='Số Câu Sai',
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

    @api.constrains('exam_id')
    def _check_exam_status(self):
        for record in self:
            if record.exam_id and record.exam_id.status != 'active':
                raise exceptions.ValidationError(
                    f"Đề thi '{record.exam_id.name}' đã đóng hoặc chưa được kích hoạt! Vui lòng chỉ chọn đề thi đang ở trạng thái 'Đang Hoạt Động'."
                )

    @api.depends('start_time', 'time_limit_minutes')
    def _compute_deadline(self):
        for record in self:
            if record.start_time and record.time_limit_minutes:
                record.deadline = record.start_time + timedelta(minutes=record.time_limit_minutes)
            else:
                record.deadline = False

    @api.depends('student_id.class_id')
    def _compute_class_id(self):
        for record in self:
            if record.student_id and record.student_id.class_id:
                record.class_id = record.student_id.class_id

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id and self.student_id.class_id:
            self.class_id = self.student_id.class_id

    @api.onchange('exam_id')
    def _onchange_exam_id(self):
        """Khi chọn đề thi, tự động điền danh sách câu hỏi của đề thi vào bài làm"""
        self.answer_ids = [Command.clear()]
        if self.exam_id:
            lines = [
                Command.create({
                    'question_id': question.id,
                    'answer_given': '',
                })
                for question in self.exam_id.question_ids
            ]
            self.answer_ids = lines

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 1. Tự động lấy class_id từ học sinh nếu chưa có
            if vals.get('student_id') and not vals.get('class_id'):
                student = self.env['school.student'].browse(vals['student_id'])
                if student.class_id:
                    vals['class_id'] = student.class_id.id

            # 2. Tự động nạp bộ câu hỏi từ exam_id nếu chưa có answer_ids
            if vals.get('exam_id') and not vals.get('answer_ids'):
                exam = self.env['exam.exam'].browse(vals['exam_id'])
                vals['answer_ids'] = [
                    Command.create({'question_id': q.id, 'answer_given': ''})
                    for q in exam.question_ids
                ]
        return super().create(vals_list)

    @api.constrains('start_time', 'end_time')
    def _check_exam_times(self):
        for record in self:
            if record.start_time and record.end_time and record.end_time < record.start_time:
                raise exceptions.ValidationError("Thời gian nộp bài phải sau thời gian bắt đầu làm bài!")

    @api.depends('student_id.name', 'exam_id.name')
    def _compute_name(self):
        for record in self:
            record.name = f"{record.student_id.name or ''} - {record.exam_id.name or ''}"

    @api.depends('status', 'answer_ids.points_earned', 'answer_ids.is_correct', 'total_possible', 'answer_ids')
    def _compute_scores(self):
        for record in self:
            answers = record.answer_ids
            total_q = len(answers)
            # Học sinh không được nhìn thấy Tỷ lệ, Số câu đúng/sai, Điểm đạt được khi đang làm bài
            if record.status != 'Graded':
                record.total_score = 0.0
                record.correct_count = 0
                record.wrong_count = 0
                record.percentage = 0.0
                continue

            correct_answers = answers.filtered(lambda a: a.is_correct)
            record.correct_count = len(correct_answers)
            record.wrong_count = total_q - record.correct_count

            if total_q > 0 and record.total_possible and record.total_possible > 0:
                # Phương thức tính điểm chuẩn: Điểm mỗi câu = total_possible / total_questions (Ví dụ: 10 / 40 = 0.25)
                point_per_q = record.total_possible / total_q
                record.total_score = round(record.correct_count * point_per_q, 2)
                record.percentage = round((record.correct_count / total_q) * 100.0, 1)
            else:
                record.total_score = round(sum(ans.points_earned for ans in answers), 2)
                if record.total_possible and record.total_possible > 0:
                    record.percentage = round((record.total_score / record.total_possible) * 100.0, 1)
                else:
                    record.percentage = 0.0

    def action_start_exam(self):
        """Bắt đầu tính giờ làm bài cho học sinh"""
        for record in self:
            if record.status != 'NotStarted':
                raise exceptions.UserError("Bài thi này đã bắt đầu hoặc đã hoàn thành!")
            record.write({
                'start_time': fields.Datetime.now(),
                'status': 'InProgress',
            })

    def action_submit_exam(self):
        self.ensure_one()
        if not self.start_time:
            self.start_time = fields.Datetime.now()
        self.end_time = fields.Datetime.now()
        self.status = 'Graded'
        
        # Đảm bảo chấm lại điểm toàn bộ bài thi
        for answer in self.answer_ids:
            answer._compute_evaluation()
        self._compute_scores()

        # Tạo hoặc lấy bản ghi AI Analysis
        analysis = self.env['ai.analysis'].search([('session_id', '=', self.id)], limit=1)
        if not analysis:
            analysis = self.env['ai.analysis'].create({
                'session_id': self.id,
                'student_id': self.student_id.id,
                'status': 'pending',
            })

        # Tự động gọi AI nếu được kích hoạt
        if self.auto_analyze:
            try:
                analysis.action_analyze_with_claude()
            except Exception as e:
                _logger.warning(f"Không thể tự động phân tích AI cho phiên {self.id}: {str(e)}")

    @api.model
    def cron_auto_submit_expired_sessions(self):
        """Tự động nộp bài và chấm điểm các phiên thi đã hết hạn làm bài"""
        now = fields.Datetime.now()
        expired_sessions = self.search([
            ('status', '=', 'InProgress'),
            ('deadline', '<=', now),
        ])
        for session in expired_sessions:
            _logger.info(f"Cron: Tự động nộp bài cho phiên thi quá hạn {session.id} ({session.name})")
            try:
                session.action_submit_exam()
            except Exception as e:
                _logger.error(f"Lỗi tự động nộp bài cho phiên {session.id}: {str(e)}")


class ExamAnswer(models.Model):
    _name = 'exam.answer'
    _description = 'Chi Tiết Đáp Án'

    _sql_constraints = [
        ('unique_session_question', 'UNIQUE(session_id, question_id)', 'Một câu hỏi chỉ được trả lời 1 lần trong một lượt làm bài!'),
    ]

    session_id = fields.Many2one('exam.session', string='Phiên Thi', required=True, ondelete='cascade')
    question_id = fields.Many2one('exam.question', string='Câu Hỏi', required=True, ondelete='cascade')
    
    # Các trường liên kết để học sinh tiện đọc đề bài trên cùng một dòng
    question_content = fields.Text(string='Đề Bài', related='question_id.content', readonly=True)
    question_type = fields.Selection(string='Dạng Câu Hỏi', related='question_id.question_type', readonly=True)
    question_points = fields.Float(
        string='Thang Điểm', 
        compute='_compute_question_points', 
        store=True,
        help='Thang điểm chuẩn của câu hỏi (tổng điểm / số câu)'
    )
    
    answer_given = fields.Char(string='Đáp Án Của Học Sinh')
    is_correct = fields.Boolean(string='Đúng/Sai', compute='_compute_evaluation', store=True)
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
        """Đảm bảo câu hỏi bắt buộc phải nằm trong Đề thi của lượt thi này!"""
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
        m = re.search(r'\b([A-Da-d])\b', str(val).strip())
        if m:
            return m.group(1).upper()
        return str(val).strip().upper()

    @staticmethod
    def _extract_number(val):
        if not val:
            return None
        val_clean = str(val).strip().replace(',', '.')
        m = re.search(r'[-+]?\d+(?:\.\d+)?', val_clean)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
        return None

    @api.depends('answer_given', 'question_id.correct_answer', 'question_points',
                 'question_id.question_type', 'question_id.acceptable_answers', 'question_id.tolerance',
                 'session_id.status')
    def _compute_evaluation(self):
        for record in self:
            # Chỉ hiển thị kết quả đúng/sai và điểm khi bài thi đã được chấm (Graded)
            if not record.session_id or record.session_id.status != 'Graded':
                record.is_correct = False
                record.points_earned = 0.0
                continue

            q = record.question_id
            if not record.answer_given or not q or not q.correct_answer:
                record.is_correct = False
                record.points_earned = 0.0
                continue

            s_raw = str(record.answer_given).strip()
            c_raw = str(q.correct_answer).strip()
            pts = record.question_points if record.question_points > 0 else (q.points or 1.0)

            # 1. So khớp trực tiếp (bỏ qua hoa thường)
            if s_raw.lower() == c_raw.lower():
                record.is_correct = True
                record.points_earned = pts
                continue

            # 2. So khớp với danh sách đáp án chấp nhận (ngăn cách bởi | hoặc ;)
            all_correct = [c_raw]
            for source in [q.correct_answer, q.acceptable_answers]:
                if source:
                    for alt in re.split(r'[|;]', str(source)):
                        alt_clean = alt.strip()
                        if alt_clean and alt_clean not in all_correct:
                            all_correct.append(alt_clean)

            if any(s_raw.lower() == alt.lower() for alt in all_correct):
                record.is_correct = True
                record.points_earned = pts
                continue

            # 3. So khớp theo dạng câu hỏi
            is_matched = False
            q_type = q.question_type or 'numeric'

            if q_type == 'single_choice':
                s_choice = self._normalize_choice(s_raw)
                c_choice = self._normalize_choice(c_raw)
                if s_choice and c_choice and s_choice == c_choice:
                    is_matched = True

            elif q_type == 'numeric':
                s_num = self._extract_number(s_raw)
                c_num = self._extract_number(c_raw)
                if s_num is not None and c_num is not None:
                    tol = q.tolerance or 0.0
                    if abs(s_num - c_num) <= tol:
                        is_matched = True

            if is_matched:
                record.is_correct = True
                record.points_earned = pts
            else:
                record.is_correct = False
                record.points_earned = 0.0


class ExamAssignWizard(models.TransientModel):
    _name = 'exam.assign.wizard'
    _description = 'Wizard Gán Đề Thi Cho Học Sinh'

    exam_id = fields.Many2one('exam.exam', string='Đề Thi Cần Gán', required=True, readonly=True)
    assign_type = fields.Selection([
        ('class', 'Gán Cho Toàn Bộ Lớp Học'),
        ('students', 'Chọn Từng Học Sinh'),
    ], string='Hình Thức Gán', default='class', required=True)
    class_id = fields.Many2one('school.class', string='Lớp Học')
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
        """Thực hiện phát đề thi: Tạo sẵn các lượt làm bài kèm câu hỏi cho học sinh"""
        self.ensure_one()
        students = self.env['school.student']
        if self.assign_type == 'class':
            if not self.class_id:
                raise exceptions.UserError("Vui lòng chọn lớp học để gán đề thi!")
            students = self.class_id.student_ids.filtered(lambda s: s.status == 'Active')
            if not students:
                raise exceptions.UserError(f"Lớp {self.class_id.name} chưa có học sinh nào đang học!")
        else:
            if not self.student_ids:
                raise exceptions.UserError("Vui lòng chọn ít nhất 1 học sinh!")
            students = self.student_ids

        created_sessions = self.env['exam.session']
        skipped_names = []

        for student in students:
            # Kiểm tra xem học sinh đã có lượt làm bài cho đề này chưa
            existing = self.env['exam.session'].search([
                ('student_id', '=', student.id),
                ('exam_id', '=', self.exam_id.id)
            ], limit=1)
            if existing:
                skipped_names.append(student.name)
                continue

            # Tạo lượt làm bài (câu hỏi sẽ tự động được sinh ra trong create())
            session = self.env['exam.session'].create({
                'student_id': student.id,
                'exam_id': self.exam_id.id,
                'class_id': student.class_id.id,
                'status': 'NotStarted',
            })
            created_sessions |= session

        msg = f"Đã gán đề thi '{self.exam_id.name}' cho {len(created_sessions)} học sinh thành công!"
        if skipped_names:
            msg += f"\n(Bỏ qua {len(skipped_names)} học sinh đã được gán trước đó: {', '.join(skipped_names)})"

        action = self.env['ir.actions.act_window']._for_xml_id('educational_system.action_exam_session')
        action.update({
            'name': f'Lượt Làm Bài - {self.exam_id.name}',
            'domain': [('exam_id', '=', self.exam_id.id)],
            'context': {'default_exam_id': self.exam_id.id},
        })
        return action