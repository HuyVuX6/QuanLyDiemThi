# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions


class SchoolGrade(models.Model):
    _name = 'school.grade'
    _description = 'Khối Lớp'
    _rec_name = 'name'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã khối phải là duy nhất!'),
    ]

    code = fields.Char(string='Mã Khối', required=True, size=20)
    name = fields.Char(string='Tên Khối', required=True, size=120)
    description = fields.Text(string='Mô Tả')
    status = fields.Selection([
        ('active', 'Đang Hoạt Động'),
        ('inactive', 'Ngừng Hoạt Động')
    ], string='Trạng Thái', default='active')
    class_ids = fields.One2many('school.class', 'grade_id', string='Các Lớp Học')
    student_ids = fields.One2many('school.student', 'grade_id', string='Học Sinh Thuộc Khối')
    question_ids = fields.One2many('exam.question', 'grade_id', string='Ngân Hàng Câu Hỏi Của Khối')
    exam_ids = fields.One2many('exam.exam', 'grade_id', string='Đề Thi Của Khối')

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"


class SchoolClass(models.Model):
    _name = 'school.class'
    _description = 'Lớp Học'
    _rec_name = 'name'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã lớp phải là duy nhất!'),
        ('max_students_pos', 'CHECK(max_students > 0)', 'Sĩ số tối đa phải lớn hơn 0!'),
    ]

    code = fields.Char(string='Mã Lớp', required=True, size=20)
    name = fields.Char(string='Tên Lớp', required=True, size=120)
    start_date = fields.Date(string='Ngày Bắt Đầu')
    end_date = fields.Date(string='Ngày Kết Thúc')
    start_end_period = fields.Char(
        string='Tháng Năm Bắt Đầu / Kết Thúc',
        compute='_compute_start_end_period',
        store=True,
        help='Thời gian năm học theo định dạng tháng/năm'
    )
    max_students = fields.Integer(string='Sĩ Số Tối Đa', default=30)
    current_students = fields.Integer(
        string='Sĩ Số Hiện Tại',
        compute='_compute_current_students',
        store=True
    )
    status = fields.Selection([
        ('active', 'Đang Hoạt Động'),
        ('inactive', 'Tạm Ngưng'),
        ('completed', 'Đã Kết Thúc')
    ], string='Trạng Thái', default='active')
    grade_id = fields.Many2one('school.grade', string='Khối Lớp', required=True, ondelete='cascade', index=True)
    teacher_id = fields.Many2one('school.instructor', string='Giáo Viên Chủ Nhiệm', ondelete='set null')
    student_ids = fields.One2many(
        'school.student',
        'class_id',
        string='Danh Sách Học Sinh'
    )
    batch_ids = fields.One2many('exam.batch', 'class_id', string='Các Đợt Kiểm Tra')
    batch_count = fields.Integer(string='Số Đợt Kiểm Tra', compute='_compute_batch_count')
    session_ids = fields.One2many('exam.session', 'class_id', string='Bài Thi Thực Hiện Tại Lớp')
    average_score = fields.Float(
        string='ĐiểmTB Lớp',
        compute='_compute_class_stats',
        store=True,
        digits=(3, 2),
        help='Điểm trung bình cộng các bài kiểm tra đã chấm tại lớp này'
    )
    total_exams_taken = fields.Integer(
        string='Số Bài Đã Chấm',
        compute='_compute_class_stats',
        store=True
    )

    @api.depends('start_date', 'end_date')
    def _compute_start_end_period(self):
        for record in self:
            s = record.start_date.strftime('%m/%Y') if record.start_date else '...'
            e = record.end_date.strftime('%m/%Y') if record.end_date else '...'
            record.start_end_period = f"{s} - {e}"

    @api.depends('batch_ids')
    def _compute_batch_count(self):
        for record in self:
            record.batch_count = len(record.batch_ids)

    def action_create_exam_batch(self):
        """Tạo nhanh đợt kiểm tra mới gán trực tiếp cho lớp này (tự động lọc đề cùng Khối lớp)"""
        self.ensure_one()
        default_code = f"KT-{self.code or 'LOP'}-{fields.Date.today().strftime('%Y%m')}"
        default_name = f"Kiểm Tra - {self.name}"
        domain = [('status', '=', 'active')]
        if self.grade_id:
            domain += ['|', ('grade_id', '=', self.grade_id.id), ('grade_id', '=', False)]
        first_exam = self.env['exam.exam'].search(domain, limit=1)
        return {
            'name': f'Tạo Đợt Kiểm Tra Mới: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.batch',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_class_id': self.id,
                'default_name': default_name,
                'default_code': default_code,
                'default_exam_id': first_exam.id if first_exam else False,
            }
        }

    def action_view_class_batches(self):
        """Xem lịch sử tất cả các đợt kiểm tra của lớp này"""
        self.ensure_one()
        return {
            'name': f'Lịch Sử Đợt Kiểm Tra - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.batch',
            'view_mode': 'list,form',
            'domain': [('class_id', '=', self.id)],
            'context': {'default_class_id': self.id},
        }

    def action_print_blank_omr_sheet(self):
        """Tải về file PDF Phiếu trả lời trắc nghiệm trắng (50 câu) trực tiếp từ lớp học để photocopy phát cho học sinh"""
        self.ensure_one()
        batch = self.batch_ids[:1]
        batch_id = batch.id if batch else 0
        return {
            'type': 'ir.actions.act_url',
            'url': f"/educational_system/download_answer_sheet/{batch_id}?mode=blank",
            'target': 'self',
        }

    @api.depends('session_ids.total_score', 'session_ids.status')
    def _compute_class_stats(self):
        for record in self:
            graded = record.session_ids.filtered(lambda s: s.status == 'Graded')
            record.total_exams_taken = len(graded)
            if graded:
                record.average_score = round(sum(graded.mapped('total_score')) / len(graded), 2)
            else:
                record.average_score = 0.0

    def action_open_add_students_wizard(self):
        """Mở cửa sổ Wizard để chọn và thêm nhiều học sinh cùng khối vào lớp"""
        self.ensure_one()
        if self.status == 'completed':
            raise exceptions.UserError("Lớp học này đã kết thúc, không thể thêm học sinh!")
        return {
            'name': f'Thêm Học Sinh Vào Lớp: {self.name} ({self.grade_id.name})',
            'type': 'ir.actions.act_window',
            'res_model': 'school.class.add.student.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_class_id': self.id,
            }
        }

    @api.depends('student_ids.status')
    def _compute_current_students(self):
        for record in self:
            record.current_students = len(record.student_ids.filtered(lambda s: s.status == 'Active'))

    @api.constrains('current_students', 'max_students')
    def _check_max_students(self):
        for record in self:
            if record.max_students > 0 and record.current_students > record.max_students:
                raise exceptions.ValidationError(
                    f"Sĩ số hiện tại ({record.current_students}) vượt quá sĩ số tối đa ({record.max_students}) của lớp {record.name}!"
                )

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"


class SchoolStudent(models.Model):
    _name = 'school.student'
    _description = 'Hồ Sơ Học Sinh'
    _rec_name = 'name'
    _rec_names_search = ['code', 'name', 'parent_phone']

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã học sinh phải là duy nhất!'),
    ]

    @api.model
    def _default_grade_id(self):
        grade = self.env['school.grade'].search([('code', '=', 'KHOI_3')], limit=1)
        if not grade:
            grade = self.env['school.grade'].search([('status', '=', 'active')], limit=1)
        return grade.id if grade else False

    code = fields.Char(string='Mã Học Sinh (MSSV)', required=True, size=20)
    name = fields.Char(string='Tên Học Sinh', required=True, size=120)
    grade_id = fields.Many2one(
        'school.grade',
        string='Khối Lớp',
        default=_default_grade_id,
        ondelete='restrict',
        index=True,
        help='Khối lớp của học sinh (ví dụ: KHOI_1, KHOI_2, KHOI_3...)'
    )
    class_id = fields.Many2one(
        'school.class',
        string='Lớp Học Hiện Tại',
        required=False,
        ondelete='set null',
        index=True,
        domain="[('grade_id', '=', grade_id)]"
    )
    date_of_birth = fields.Date(string='Ngày Sinh')
    gender = fields.Selection([('M', 'Nam'), ('F', 'Nữ'), ('O', 'Khác')], string='Giới Tính', default='M')
    parent_phone = fields.Char(string='Điện Thoại Phụ Huynh', size=20)
    email = fields.Char(string='Email Phụ Huynh')
    user_id = fields.Many2one('res.users', string='Tài Khoản Liên Kết (Không bắt buộc)', ondelete='set null')
    status = fields.Selection([
        ('Active', 'Đang Học'),
        ('Inactive', 'Tạm Ngưng'),
        ('Graduated', 'Đã Hoàn Thành / Chuyển Trường')
    ], default='Active', string='Trạng Thái')

    # Điểm thi & lịch sử bài kiểm tra đi theo học sinh (dù học sinh chuyển lớp điểm vẫn giữ nguyên)
    session_ids = fields.One2many(
        'exam.session',
        'student_id',
        string='Kết Quả Các Bài Kiểm Tra'
    )
    analysis_ids = fields.One2many(
        'ai.analysis',
        'student_id',
        string='Lịch Sử Phân Tích AI'
    )
    exam_count = fields.Integer(
        string='Số Bài Đã Chấm',
        compute='_compute_student_exam_stats',
        store=True
    )
    passed_count = fields.Integer(
        string='Số Bài Đạt',
        compute='_compute_student_exam_stats',
        store=True
    )
    failed_count = fields.Integer(
        string='Số Bài Chưa Đạt',
        compute='_compute_student_exam_stats',
        store=True
    )
    average_score = fields.Float(
        string='Điểm TB Tích Lũy',
        compute='_compute_student_exam_stats',
        store=True,
        digits=(3, 2),
        help='Điểm trung bình tích lũy của học sinh qua tất cả các bài kiểm tra (đi theo học sinh khi chuyển lớp)'
    )

    @api.depends('session_ids.status', 'session_ids.total_score', 'session_ids.passed')
    def _compute_student_exam_stats(self):
        for record in self:
            graded = record.session_ids.filtered(lambda s: s.status == 'Graded')
            record.exam_count = len(graded)
            if graded:
                passed = graded.filtered(lambda s: s.passed)
                record.passed_count = len(passed)
                record.failed_count = len(graded) - len(passed)
                record.average_score = round(sum(graded.mapped('total_score')) / len(graded), 2)
            else:
                record.passed_count = 0
                record.failed_count = 0
                record.average_score = 0.0

    @api.onchange('class_id')
    def _onchange_class_id_sync_grade(self):
        if self.class_id and self.class_id.grade_id:
            self.grade_id = self.class_id.grade_id

    @api.constrains('grade_id', 'class_id')
    def _check_student_grade_match_class(self):
        for record in self:
            if record.class_id and record.grade_id and record.class_id.grade_id != record.grade_id:
                raise exceptions.ValidationError(
                    f"Học sinh '{record.name}' đang thuộc '{record.grade_id.name}' không thể xếp vào lớp '{record.class_id.name}' thuộc '{record.class_id.grade_id.name}'! "
                    f"Vui lòng chuyển Khối lớp của học sinh trước khi xếp lớp."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('class_id') and not vals.get('grade_id'):
                cls = self.env['school.class'].browse(vals['class_id'])
                if cls.exists() and cls.grade_id:
                    vals['grade_id'] = cls.grade_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('class_id') and 'grade_id' not in vals:
            cls = self.env['school.class'].browse(vals['class_id'])
            if cls.exists() and cls.grade_id:
                vals = dict(vals, grade_id=cls.grade_id.id)
        return super().write(vals)

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        if name:
            domain = ['|', ('code', operator, name), ('name', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)

    def _compute_display_name(self):
        for record in self:
            class_str = f" ({record.class_id.name})" if record.class_id else " (Chưa có lớp)"
            record.display_name = f"[{record.code}] {record.name}{class_str}"

    def action_remove_from_class(self):
        """Gỡ học sinh ra khỏi lớp hiện tại mà vẫn giữ nguyên hồ sơ và toàn bộ lịch sử điểm thi của học sinh"""
        for record in self:
            record.class_id = False


class SchoolInstructor(models.Model):
    _name = 'school.instructor'
    _description = 'Hồ Sơ Giáo Viên'
    _rec_name = 'name'

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã giáo viên phải là duy nhất!'),
    ]

    code = fields.Char(string='Mã Giáo Viên', required=True, size=20)
    name = fields.Char(string='Tên Giáo Viên', required=True, size=120)
    specialization = fields.Char(string='Chuyên Môn', default='Toán tiểu học')
    phone = fields.Char(string='Số Điện Thoại')
    email = fields.Char(string='Email')
    user_id = fields.Many2one('res.users', string='Tài Khoản Odoo Liên Kết', ondelete='set null')
    status = fields.Selection([
        ('Active', 'Đang Dạy'),
        ('Inactive', 'Tạm Ngưng'),
        ('Retired', 'Đã Nghỉ')
    ], default='Active', string='Trạng Thái')
    class_ids = fields.One2many('school.class', 'teacher_id', string='Lớp Chủ Nhiệm')

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"


class SchoolClassAddStudentWizard(models.TransientModel):
    _name = 'school.class.add.student.wizard'
    _description = 'Wizard Thêm Học Sinh Vào Lớp Học'

    class_id = fields.Many2one('school.class', string='Lớp Học Tiếp Nhận', required=True, readonly=True)
    grade_id = fields.Many2one('school.grade', related='class_id.grade_id', string='Khối Lớp', readonly=True)
    filter_type = fields.Selection([
        ('unassigned', 'Chỉ học sinh cùng Khối chưa có lớp'),
        ('all', 'Tất cả học sinh cùng Khối (kể cả đang ở lớp khác để chuyển lớp)'),
    ], string='Bộ Lọc Đối Tượng', default='unassigned', required=True)
    search_keyword = fields.Char(string='Tìm Kiếm Học Sinh')
    filter_info = fields.Char(string='Thống Kê Khả Dụng', compute='_compute_filter_info')
    line_ids = fields.One2many(
        'school.class.add.student.wizard.line',
        'wizard_id',
        string='Danh Sách Học Sinh Có Thể Thêm'
    )
    selected_student_ids = fields.Many2many('school.student', string='Tất Cả Học Sinh Đã Chọn')
    selected_count = fields.Integer(string='Đã Chọn', compute='_compute_selected_count')

    def _build_student_domain(self, cls, filter_type, keyword=""):
        domain = [('status', '=', 'Active')]
        if cls and cls.grade_id:
            domain += ['|', ('grade_id', '=', cls.grade_id.id), ('grade_id', '=', False)]
        if filter_type == 'unassigned':
            domain.append(('class_id', '=', False))
        elif cls:
            domain.append(('class_id', '!=', cls.id))
        kw = (keyword or '').strip()
        if kw:
            domain += [
                '|', '|',
                ('code', 'ilike', kw),
                ('name', 'ilike', kw),
                ('parent_phone', 'ilike', kw)
            ]
        return domain

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        class_id = res.get('class_id') or self.env.context.get('default_class_id') or self.env.context.get('active_id')
        if class_id and 'line_ids' in fields_list:
            cls = self.env['school.class'].browse(class_id)
            students = self.env['school.student'].search(
                self._build_student_domain(cls, 'unassigned'), order='code, name'
            )
            if not students:
                students = self.env['school.student'].search(
                    self._build_student_domain(cls, 'all'), order='code, name'
                )
                res['filter_type'] = 'all'

            res['line_ids'] = [(0, 0, {'student_id': s.id, 'selected': False}) for s in students]
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            class_id = vals.get('class_id') or self.env.context.get('default_class_id') or self.env.context.get('active_id')
            if class_id and not vals.get('line_ids'):
                cls = self.env['school.class'].browse(class_id)
                f_type = vals.get('filter_type', 'unassigned')
                students = self.env['school.student'].search(
                    self._build_student_domain(cls, f_type), order='code, name'
                )
                if not students and f_type == 'unassigned':
                    students = self.env['school.student'].search(
                        self._build_student_domain(cls, 'all'), order='code, name'
                    )
                    vals['filter_type'] = 'all'
                vals['line_ids'] = [(0, 0, {'student_id': s.id, 'selected': False}) for s in students]
        return super().create(vals_list)

    def _get_all_selected_students(self):
        self.ensure_one()
        visible_checked = self.line_ids.filtered('selected').mapped('student_id')
        visible_unchecked = self.line_ids.filtered(lambda l: not l.selected).mapped('student_id')
        return (self.selected_student_ids - visible_unchecked) | visible_checked

    @api.depends('line_ids.selected', 'selected_student_ids')
    def _compute_selected_count(self):
        for wizard in self:
            wizard.selected_count = len(wizard._get_all_selected_students())

    @api.depends('filter_type', 'class_id', 'line_ids', 'selected_count')
    def _compute_filter_info(self):
        for wizard in self:
            visible_count = len(wizard.line_ids)
            wizard.filter_info = f"📋 Đang hiển thị: {visible_count} học sinh ({wizard.grade_id.name or ''}) | 🎯 Đã chọn: {wizard.selected_count} học sinh"

    @api.onchange('search_keyword', 'filter_type')
    def _onchange_search_or_filter(self):
        for line in self.line_ids:
            if line.student_id:
                if line.selected:
                    self.selected_student_ids |= line.student_id
                else:
                    self.selected_student_ids -= line.student_id

        domain = self._build_student_domain(self.class_id, self.filter_type, self.search_keyword)
        students = self.env['school.student'].search(domain, order='code, name', limit=200)

        new_lines = [
            (0, 0, {'student_id': s.id, 'selected': s in self.selected_student_ids})
            for s in students
        ]
        self.line_ids = [(5, 0, 0)] + new_lines

    def action_select_all(self):
        self.ensure_one()
        self.line_ids.write({'selected': True})
        all_students = self.line_ids.mapped('student_id')
        self.write({'selected_student_ids': [(6, 0, (self.selected_student_ids | all_students).ids)]})
        return {
            'name': f'Thêm Học Sinh Vào Lớp: {self.class_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, default_class_id=self.class_id.id),
        }

    def action_deselect_all(self):
        self.ensure_one()
        self.line_ids.write({'selected': False})
        self.write({'selected_student_ids': [(5, 0, 0)]})
        return {
            'name': f'Thêm Học Sinh Vào Lớp: {self.class_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, default_class_id=self.class_id.id),
        }

    def action_add_students(self):
        """Thêm hoặc chuyển các học sinh đã chọn vào lớp học hiện tại (giữ nguyên toàn bộ lịch sử điểm số)"""
        self.ensure_one()
        selected_students = self._get_all_selected_students()
        if not selected_students:
            raise exceptions.UserError("Vui lòng tích chọn ít nhất một học sinh trong danh sách để thêm vào lớp!")

        new_total = self.class_id.current_students + len(selected_students)
        if self.class_id.max_students > 0 and new_total > self.class_id.max_students:
            raise exceptions.UserError(
                f"Không thể thêm! Sĩ số hiện tại ({self.class_id.current_students}) + {len(selected_students)} HS "
                f"sẽ vượt quá sĩ số tối đa ({self.class_id.max_students}) của lớp {self.class_id.name}!"
            )

        selected_students.write({
            'grade_id': self.class_id.grade_id.id,
            'class_id': self.class_id.id,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f"Đã xếp thành công {len(selected_students)} học sinh vào lớp {self.class_id.name}!",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }


class SchoolClassAddStudentWizardLine(models.TransientModel):
    _name = 'school.class.add.student.wizard.line'
    _description = 'Dòng Học Sinh Trong Wizard Thêm Vào Lớp'

    wizard_id = fields.Many2one('school.class.add.student.wizard', string='Wizard', ondelete='cascade')
    selected = fields.Boolean(string='Chọn', default=False)
    student_id = fields.Many2one('school.student', string='Học Sinh', required=True, ondelete='cascade')
    code = fields.Char(related='student_id.code', string='MSSV / Mã Học Sinh', readonly=True)
    name = fields.Char(related='student_id.name', string='Họ Và Tên', readonly=True)
    grade_id = fields.Many2one('school.grade', related='student_id.grade_id', string='Khối', readonly=True)
    gender = fields.Selection(related='student_id.gender', string='Giới Tính', readonly=True)
    date_of_birth = fields.Date(related='student_id.date_of_birth', string='Ngày Sinh', readonly=True)
    current_class_name = fields.Char(string='Lớp Hiện Tại', compute='_compute_current_class_name')
    parent_phone = fields.Char(related='student_id.parent_phone', string='SĐT Phụ Huynh', readonly=True)

    @api.depends('student_id.class_id')
    def _compute_current_class_name(self):
        for line in self:
            line.current_class_name = line.student_id.class_id.name if line.student_id.class_id else "Chưa có lớp"
