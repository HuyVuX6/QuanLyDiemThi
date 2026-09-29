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
    max_students = fields.Integer(string='Sĩ Số Tối Đa', default=30)
    current_students = fields.Integer(
        string='Sĩ Số Hiện Tại',
        compute='_compute_current_students',
        store=True
    )
    grade_id = fields.Many2one('school.grade', string='Khối Lớp', required=True, ondelete='cascade')
    teacher_id = fields.Many2one('school.instructor', string='Giáo Viên Chủ Nhiệm', ondelete='set null')
    student_ids = fields.One2many('school.student', 'class_id', string='Danh Sách Học Sinh')

    @api.depends('student_ids.status')
    def _compute_current_students(self):
        for record in self:
            record.current_students = len(record.student_ids.filtered(lambda s: s.status == 'Active'))

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
    status = fields.Selection([
        ('Active', 'Đang Học'),
        ('Inactive', 'Tạm Ngừng'),
        ('Graduated', 'Đã Tốt Nghiệp')
    ], default='Active', string='Trạng Thái')
    class_id = fields.Many2one('school.class', string='Lớp Học', required=True, ondelete='cascade')

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"


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
    status = fields.Selection([('Active', 'Đang Dạy'), ('Inactive', 'Nghỉ')], default='Active', string='Trạng Thái')

    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"