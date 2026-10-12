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
    class_ids = fields.One2many('school.class', 'grade_id', string='Các Lớp')

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
    grade_id = fields.Many2one('school.grade', string='Khối Lớp', required=True, ondelete='cascade')
    teacher_id = fields.Many2one('school.instructor', string='Giáo Viên Chủ Nhiệm', ondelete='set null')
    student_ids = fields.One2many('school.student', 'class_id', string='Danh Sách Học Sinh')
    batch_ids = fields.One2many('exam.batch', 'class_id', string='Các Đợt Kiểm Tra')
    session_ids = fields.One2many('exam.session', 'class_id', string='Kết Quả Kiểm Tra Của Lớp')

    def action_open_add_students_wizard(self):
        """Mở wizard thêm học sinh vào lớp học"""
        self.ensure_one()
        return {
            'name': f'Thêm Học Sinh Vào Lớp: {self.name}',
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

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã học sinh phải là duy nhất!'),
    ]

    code = fields.Char(string='Mã Học Sinh', required=True, size=20)
    name = fields.Char(string='Tên Học Sinh', required=True, size=120)
    date_of_birth = fields.Date(string='Ngày Sinh')
    gender = fields.Selection([('M', 'Nam'), ('F', 'Nữ'), ('O', 'Khác')], string='Giới Tính', default='M')
    parent_phone = fields.Char(string='Điện Thoại Phụ Huynh', size=20)
    email = fields.Char(string='Email')
    user_id = fields.Many2one('res.users', string='Tài Khoản Liên Kết', ondelete='set null')
    status = fields.Selection([
        ('Active', 'Đang Học'),
        ('Inactive', 'Tạm Ngừng'),
        ('Graduated', 'Đã Tốt Nghiệp')
    ], default='Active', string='Trạng Thái')
    # Tương tự như giáo viên, học sinh được tạo độc lập và chỉ được phân/thêm vào lớp tại giao diện LỚP HỌC
    class_id = fields.Many2one('school.class', string='Lớp Học', required=False, ondelete='set null')

    def _compute_display_name(self):
        for record in self:
            class_str = f" ({record.class_id.name})" if record.class_id else " (Chưa có lớp)"
            record.display_name = f"[{record.code}] {record.name}{class_str}"

    def action_remove_from_class(self):
        """Gỡ học sinh ra khỏi lớp hiện tại mà vẫn giữ nguyên hồ sơ học sinh"""
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
    user_id = fields.Many2one('res.users', string='Tài Khoản Liên Kết', ondelete='set null')
    status = fields.Selection([('Active', 'Đang Dạy'), ('Inactive', 'Nghỉ')], default='Active', string='Trạng Thái')
    class_ids = fields.One2many('school.class', 'teacher_id', string='Lớp Chủ Nhiệm')

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"


class SchoolClassAddStudentWizard(models.TransientModel):
    _name = 'school.class.add.student.wizard'
    _description = 'Wizard Thêm Học Sinh Vào Lớp Học'

    class_id = fields.Many2one('school.class', string='Lớp Học Tiếp Nhận', required=True, readonly=True)
    filter_type = fields.Selection([
        ('unassigned', 'Chỉ học sinh chưa có lớp'),
        ('all', 'Tất cả học sinh (kể cả học sinh đang ở lớp khác)'),
    ], string='Bộ Lọc Học Sinh', default='unassigned', required=True)
    filter_info = fields.Char(string='Thống Kê Khả Dụng', compute='_compute_filter_info')
    student_ids = fields.Many2many(
        'school.student',
        string='Danh Sách Học Sinh Cần Thêm',
        required=True,
    )

    @api.depends('filter_type', 'class_id')
    def _compute_filter_info(self):
        for wizard in self:
            if not wizard.class_id:
                wizard.filter_info = ""
                continue
            if wizard.filter_type == 'unassigned':
                count = self.env['school.student'].search_count([('class_id', '=', False), ('status', '=', 'Active')])
                wizard.filter_info = f"💡 Đang có {count} học sinh đang học chưa được xếp vào lớp nào."
            else:
                count = self.env['school.student'].search_count([('class_id', '!=', wizard.class_id.id), ('status', '=', 'Active')])
                wizard.filter_info = f"💡 Đang có {count} học sinh đủ điều kiện thêm hoặc chuyển vào lớp {wizard.class_id.name}."

    @api.onchange('filter_type')
    def _onchange_filter_type(self):
        if self.filter_type == 'unassigned' and self.student_ids:
            # Tự động loại bỏ học sinh đã có lớp nếu chuyển về chế độ chỉ học sinh chưa có lớp
            self.student_ids = self.student_ids.filtered(lambda s: not s.class_id)

    def action_add_students(self):
        """Thêm các học sinh đã chọn vào lớp học hiện tại"""
        self.ensure_one()
        if not self.student_ids:
            raise exceptions.UserError("Vui lòng chọn ít nhất một học sinh để thêm vào lớp!")

        if self.filter_type == 'unassigned':
            assigned_students = self.student_ids.filtered(lambda s: s.class_id)
            if assigned_students:
                names = ', '.join(assigned_students.mapped('name'))
                raise exceptions.UserError(
                    f"Bạn đang chọn chế độ 'Chỉ học sinh chưa có lớp', nhưng các học sinh sau đã có lớp: {names}!\n"
                    f"Vui lòng chọn chế độ 'Tất cả học sinh' nếu bạn muốn chuyển lớp cho các học sinh này."
                )

        new_total = self.class_id.current_students + len(self.student_ids)
        if self.class_id.max_students > 0 and new_total > self.class_id.max_students:
            raise exceptions.UserError(
                f"Không thể thêm! Sĩ số sau khi thêm ({new_total}) sẽ vượt quá sĩ số tối đa ({self.class_id.max_students}) của lớp {self.class_id.name}!"
            )

        # Gán học sinh vào lớp này
        self.student_ids.write({'class_id': self.class_id.id})
        return {'type': 'ir.actions.act_window_close'}