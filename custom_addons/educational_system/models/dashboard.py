# -*- coding: utf-8 -*-
from odoo import models, fields, api

class EducationDashboard(models.Model):
    _name = 'education.dashboard'
    _description = 'Bảng Điều Khiển & Thống Kê Học Tập'

    name = fields.Char(string='Tiêu Đề', default='Tổng Quan Học Tập Toán Lớp 3')

    # Thống kê Quy mô Học tập
    total_students = fields.Integer(string='Tổng Số Học Sinh', compute='_compute_stats')
    active_students = fields.Integer(string='Học Sinh Đang Học', compute='_compute_stats')
    total_classes = fields.Integer(string='Tổng Số Lớp', compute='_compute_stats')
    total_instructors = fields.Integer(string='Tổng Giáo Viên', compute='_compute_stats')

    # Thống kê Đề & Câu Hỏi
    total_exams = fields.Integer(string='Tổng Đề Thi', compute='_compute_stats')
    total_questions = fields.Integer(string='Tổng Số Câu Hỏi', compute='_compute_stats')

    # Thống kê Thi Cử & Điểm Số
    total_sessions = fields.Integer(string='Lượt Làm Bài', compute='_compute_stats')
    submitted_sessions = fields.Integer(string='Bài Đã Nộp', compute='_compute_stats')
    avg_score = fields.Float(string='Điểm Trung Bình', compute='_compute_stats')
    pass_rate = fields.Float(string='Tỷ Lệ Đạt (>= 5đ)', compute='_compute_stats')
    excellent_rate = fields.Float(string='Tỷ Lệ Giỏi (>= 8đ)', compute='_compute_stats')

    # Thống kê Phân Tích AI
    total_ai = fields.Integer(string='Yêu Cầu Phân Tích', compute='_compute_stats')
    completed_ai = fields.Integer(string='AI Đã Phân Tích Xong', compute='_compute_stats')

    def _compute_stats(self):
        Student = self.env['school.student']
        Class = self.env['school.class']
        Instructor = self.env['school.instructor']
        Exam = self.env['exam.exam']
        Question = self.env['exam.question']
        Session = self.env['exam.session']
        AI = self.env['ai.analysis']

        for record in self:
            record.total_students = Student.search_count([])
            record.active_students = Student.search_count([('status', '=', 'Active')])
            record.total_classes = Class.search_count([])
            record.total_instructors = Instructor.search_count([])

            record.total_exams = Exam.search_count([])
            record.total_questions = Question.search_count([])

            sessions = Session.search([])
            record.total_sessions = len(sessions)
            submitted = sessions.filtered(lambda s: s.status in ('Submitted', 'Graded'))
            record.submitted_sessions = len(submitted)

            if submitted:
                scores = submitted.mapped('total_score')
                record.avg_score = round(sum(scores) / len(scores), 2)
                passed = len(submitted.filtered(lambda s: s.total_score >= 5.0))
                record.pass_rate = round((passed / len(submitted)) * 100, 1)
                excellent = len(submitted.filtered(lambda s: s.total_score >= 8.0))
                record.excellent_rate = round((excellent / len(submitted)) * 100, 1)
            else:
                record.avg_score = 0.0
                record.pass_rate = 0.0
                record.excellent_rate = 0.0

            record.total_ai = AI.search_count([])
            record.completed_ai = AI.search_count([('status', '=', 'completed')])

    def action_view_students(self):
        return {
            'name': 'Học Sinh',
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_classes(self):
        return {
            'name': 'Lớp Học',
            'type': 'ir.actions.act_window',
            'res_model': 'school.class',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_exams(self):
        return {
            'name': 'Đề Thi',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.exam',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_questions(self):
        return {
            'name': 'Ngân Hàng Câu Hỏi',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.question',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_sessions(self):
        return {
            'name': 'Lượt Làm Bài',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.session',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_ai(self):
        return {
            'name': 'Phân Tích AI',
            'type': 'ir.actions.act_window',
            'res_model': 'ai.analysis',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_exam_stats(self):
        return {
            'name': 'Thống Kê Điểm Thi & Bài Làm',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.session',
            'view_mode': 'graph,pivot,list,form',
            'target': 'current',
        }

    def action_view_question_stats(self):
        return {
            'name': 'Thống Kê Ngân Hàng Câu Hỏi',
            'type': 'ir.actions.act_window',
            'res_model': 'exam.question',
            'view_mode': 'graph,pivot,list,form',
            'target': 'current',
        }

    @api.model
    def action_open_dashboard(self):
        record = self.search([], limit=1)
        if not record:
            record = self.create({'name': 'Tổng Quan Học Tập Toán Lớp 3'})
        return {
            'name': 'Bảng Điều Khiển Học Tập',
            'type': 'ir.actions.act_window',
            'res_model': 'education.dashboard',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }
