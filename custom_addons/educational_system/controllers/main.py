# -*- coding: utf-8 -*-
import html as html_lib
import io
import re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from odoo import http
from odoo.http import request


class ExamQuestionTemplateController(http.Controller):

    @http.route('/educational_system/download_question_template', type='http', auth='user')
    def download_question_template(self, **kwargs):
        """Tạo và trả về trực tiếp file Excel mẫu Ngân hàng câu hỏi trắc nghiệm Toán 3"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'CauHoiTracNghiemToan3'

        navy_header_fill = PatternFill(start_color='1B365D', end_color='1B365D', fill_type='solid')
        header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
        thin_border = Border(
            left=Side(style='thin', color='CCCCCC'),
            right=Side(style='thin', color='CCCCCC'),
            top=Side(style='thin', color='CCCCCC'),
            bottom=Side(style='thin', color='CCCCCC'),
        )
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)

        headers = [
            'Mã Câu Hỏi (*)',
            'Nội Dung Câu Hỏi (*)',
            'Chủ Đề (*)',
            'Phương Án A (*)',
            'Phương Án B (*)',
            'Phương Án C (*)',
            'Phương Án D (*)',
            'Đáp Án Đúng (*) (A/B/C/D)',
            'Độ Khó',
            'Điểm',
            'Hướng Dẫn Giải',
        ]
        ws.append(headers)

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = navy_header_fill
            cell.font = header_font
            cell.alignment = center_align
            cell.border = thin_border
        ws.row_dimensions[1].height = 30

        sample_rows = [
            ['CH-TN-01', 'Tính: 345 + 218 = ?', 'Phép Cộng', '553', '563', '573', '562', 'B', 'Dễ', 1.0, '345 + 218 = 563. Đáp án đúng là B.'],
            ['CH-TN-02', 'Tính: 782 - 349 = ?', 'Phép Trừ', '433', '443', '431', '423', 'A', 'Dễ', 1.0, '782 - 349 = 433. Đáp án đúng là A.'],
            ['CH-TN-03', 'Tính nhẩm: 6 x 8 = ?', 'Phép Nhân', '42', '46', '48', '54', 'C', 'Dễ', 1.0, 'Theo bảng nhân 6: 6 x 8 = 48. Đáp án đúng là C.'],
            ['CH-TN-04', 'Tính: 72 : 9 = ?', 'Phép Chia', '7', '8', '9', '6', 'B', 'Dễ', 1.0, '72 : 9 = 8 (vì 9 x 8 = 72). Đáp án đúng là B.'],
            ['CH-TN-05', 'Một hình chữ nhật có chiều dài 8 cm, chiều rộng 5 cm. Chu vi của hình chữ nhật đó là:', 'Hình Học', '13 cm', '26 cm', '40 cm', '52 cm', 'B', 'Trung Bình', 1.0, 'Chu vi hình chữ nhật = (8 + 5) x 2 = 26 (cm). Đáp án đúng là B.'],
            ['CH-TN-06', 'Mẹ mua 5 hộp bánh, mỗi hộp có 6 cái bánh. Hỏi mẹ đã mua tất cả bao nhiêu cái bánh?', 'Toán Lời Văn', '11 cái', '25 cái', '30 cái', '35 cái', 'C', 'Trung Bình', 1.0, 'Số bánh mẹ mua là: 6 x 5 = 30 (cái bánh). Đáp án đúng là C.'],
        ]

        for row_data in sample_rows:
            ws.append(row_data)
            current_row = ws.max_row
            ws.row_dimensions[current_row].height = 24
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=current_row, column=col_idx)
                cell.font = Font(name='Arial', size=10)
                cell.border = thin_border
                # Mã, Chủ đề, PA A, B, C, D, Đáp án đúng, Độ khó, Điểm căn giữa
                if col_idx in [1, 3, 4, 5, 6, 7, 8, 9, 10]:
                    cell.alignment = center_align
                else:
                    cell.alignment = left_align

        column_widths = {
            'A': 16, 'B': 45, 'C': 16, 'D': 18, 'E': 18, 'F': 18, 'G': 18, 'H': 24, 'I': 14, 'J': 10, 'K': 35
        }
        for col_letter, width in column_widths.items():
            ws.column_dimensions[col_letter].width = width

        ws_guide = wb.create_sheet(title='HuongDan_NguyenTac')
        ws_guide.column_dimensions['A'].width = 25
        ws_guide.column_dimensions['B'].width = 70

        guide_header = ['Quy Tắc / Mục', 'Chi Tiết Hướng Dẫn & Giá Trị Hợp Lệ Cho Trắc Nghiệm']
        ws_guide.append(guide_header)
        for col_idx in range(1, 3):
            cell = ws_guide.cell(row=1, column=col_idx)
            cell.fill = navy_header_fill
            cell.font = header_font
            cell.alignment = center_align

        guide_rows = [
            ['Cột bắt buộc (*)', 'Mã Câu Hỏi, Nội Dung Câu Hỏi, Chủ Đề, Phương Án A, Phương Án B, Phương Án C, Phương Án D, Đáp Án Đúng.'],
            ['Chủ Đề hợp lệ', 'Phép Cộng (Addition), Phép Trừ (Subtraction), Phép Nhân (Multiplication), Phép Chia (Division), Hình Học (Geometry), Toán Lời Văn (WordProblem).'],
            ['Đáp Án Đúng (*)', 'Bắt buộc là một trong 4 chữ cái: A, B, C hoặc D (không phân biệt hoa/thường).'],
            ['Phương Án A, B, C, D', 'Điền nội dung của 4 lựa chọn (số hoặc chữ ngắn gọn).'],
            ['Độ Khó', 'Dễ (Easy), Trung Bình (Medium - mặc định), Khó (Hard).'],
            ['Điểm Mặc Định', 'Mặc định là 1.0 (khi đưa vào bài thi, hệ thống sẽ tự động quy chuẩn 10 điểm chia đều cho số câu).'],
            ['Xử Lý Trùng Mã', 'Tùy chọn trên giao diện: Cập nhật nếu đã có (khuyên dùng) hoặc Bỏ qua dòng trùng.'],
        ]
        for g_row in guide_rows:
            ws_guide.append(g_row)
            r = ws_guide.max_row
            ws_guide.cell(row=r, column=1).font = Font(name='Arial', size=10, bold=True)
            ws_guide.cell(row=r, column=2).font = Font(name='Arial', size=10)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        file_content = buf.getvalue()

        return request.make_response(
            file_content,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="mau_import_cau_hoi_trac_nghiem_toan_3.xlsx"'),
            ]
        )



    @http.route('/educational_system/print_exam_paper/<int:batch_id>', type='http', auth='user')
    def print_exam_paper(self, batch_id, **kwargs):
        """Render Đề Thi Trắc Nghiệm chuẩn in ấn A4 cho đợt kiểm tra"""
        batch = request.env['exam.batch'].browse(batch_id)
        if not batch.exists() or not batch.exam_id:
            return request.not_found()

        exam = batch.exam_id
        questions = exam.question_ids.sorted(key=lambda q: q.code or str(q.id))

        html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"/>
    <title>Đề Thi Trắc Nghiệm - {exam.name}</title>
    <style>
        @page {{
            size: A4 portrait;
            margin: 12mm 15mm 15mm 15mm;
        }}
        * {{
            box-sizing: border-box;
            font-family: "Times New Roman", Times, serif;
        }}
        body {{
            margin: 0;
            padding: 0;
            background: #f0f2f5;
            color: #111;
        }}
        .no-print-bar {{
            background: #1B365D;
            color: white;
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 999;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }}
        .btn-print {{
            background: #28a745;
            color: white;
            border: none;
            padding: 8px 18px;
            font-size: 14px;
            font-weight: bold;
            border-radius: 4px;
            cursor: pointer;
        }}
        .btn-print:hover {{
            background: #218838;
        }}
        .page-container {{
            width: 210mm;
            min-height: 297mm;
            padding: 15mm 18mm;
            margin: 15px auto;
            background: white;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        @media print {{
            body {{
                background: white;
            }}
            .no-print-bar {{
                display: none !important;
            }}
            .page-container {{
                box-shadow: none;
                margin: 0;
                padding: 0;
                width: 100%;
                min-height: auto;
            }}
        }}
        .header-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 12px;
        }}
        .header-table td {{
            vertical-align: top;
        }}
        .school-title {{
            text-align: center;
            font-size: 13px;
            line-height: 1.4;
        }}
        .exam-title {{
            text-align: center;
            font-size: 13.5px;
            line-height: 1.4;
        }}
        .main-heading {{
            font-size: 15px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .divider-line {{
            width: 120px;
            height: 1px;
            background: #000;
            margin: 3px auto;
        }}
        .student-meta {{
            border: 1px solid #999;
            border-radius: 4px;
            padding: 8px 12px;
            margin-bottom: 15px;
            font-size: 13.5px;
            line-height: 1.8;
            background: #fafafa;
        }}
        .instructions-box {{
            border-left: 3px solid #1B365D;
            background: #f4f7fb;
            padding: 6px 10px;
            margin-bottom: 15px;
            font-size: 12.5px;
            font-style: italic;
        }}
        .question-block {{
            margin-bottom: 14px;
            page-break-inside: avoid;
        }}
        .question-title {{
            font-size: 13.5px;
            font-weight: bold;
            margin-bottom: 5px;
            line-height: 1.4;
        }}
        .options-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 20px;
            font-size: 13px;
            padding-left: 18px;
        }}
        .opt {{
            line-height: 1.4;
        }}
        .opt-label {{
            font-weight: bold;
            margin-right: 4px;
        }}
        .exam-footer {{
            text-align: center;
            margin-top: 25px;
            font-weight: bold;
            font-size: 13px;
            letter-spacing: 2px;
        }}
    </style>
</head>
<body>
    <div class="no-print-bar">
        <div>
            <strong>Đề Thi: {exam.name}</strong> ({batch.name} - Lớp {batch.class_id.name or ''})
        </div>
        <div>
            <button class="btn-print" onclick="window.print()">🖨️ In Đề Thi Ngay (Print)</button>
        </div>
    </div>

    <div class="page-container">
        <table class="header-table">
            <tr>
                <td style="width: 48%;" class="school-title">
                    <div>PHÒNG GIÁO DỤC VÀ ĐÀO TẠO</div>
                    <div style="font-weight: bold;">TRƯỜNG TIỂU HỌC NGUYỄN BỈNH KHIÊM</div>
                    <div class="divider-line"></div>
                    <div style="margin-top: 4px; font-style: italic;">Đề thi chính thức</div>
                </td>
                <td style="width: 4%;"></td>
                <td style="width: 48%;" class="exam-title">
                    <div class="main-heading">{batch.name.upper()}</div>
                    <div style="font-weight: bold;">MÔN: TOÁN LỚP 3</div>
                    <div>Thời gian làm bài: <strong>{exam.time_limit_minutes} phút</strong></div>
                    <div style="font-style: italic; font-size: 12.5px;">(Không kể thời gian phát đề)</div>
                </td>
            </tr>
        </table>

        <div class="student-meta">
            <div style="display: flex; justify-content: space-between;">
                <div>Họ và tên thí sinh: ......................................................................................</div>
                <div>Lớp: <strong>{batch.class_id.name or '3A1'}</strong></div>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                <div>Số báo danh: ............................................................................................</div>
                <div>Mã đề thi: <strong style="border: 1px solid #000; padding: 1px 8px; font-size: 14px;">{exam.code}</strong></div>
            </div>
        </div>

        <div class="instructions-box">
            * <strong>Lưu ý quan trọng:</strong> Thí sinh <strong>KHÔNG</strong> làm bài vào tờ đề thi này. Hãy dùng bút chì đen tô kín ô tròn phương án trả lời tương ứng vào <strong>PHIẾU TRẢ LỜI TRẮC NGHIỆM</strong>. Đề thi gồm có {len(questions)} câu hỏi trắc nghiệm.
        </div>

        <div class="questions-list">
        """

        for idx, q in enumerate(questions, start=1):
            clean_content = html_lib.escape(q.content or '').replace('\n', '<br/>')
            opt_a = html_lib.escape(q.option_a or '')
            opt_b = html_lib.escape(q.option_b or '')
            opt_c = html_lib.escape(q.option_c or '')
            opt_d = html_lib.escape(q.option_d or '')
            html += f"""
            <div class="question-block">
                <div class="question-title">Câu {idx}: <span style="font-weight: normal;">{clean_content}</span></div>
                <div class="options-grid">
                    <div class="opt"><span class="opt-label">A.</span>{opt_a}</div>
                    <div class="opt"><span class="opt-label">B.</span>{opt_b}</div>
                    <div class="opt"><span class="opt-label">C.</span>{opt_c}</div>
                    <div class="opt"><span class="opt-label">D.</span>{opt_d}</div>
                </div>
            </div>
            """

        html += f"""
        </div>

        <div class="exam-footer">
            -------------------- HẾT --------------------
            <div style="font-size: 12px; font-weight: normal; margin-top: 5px; font-style: italic;">
                (Cán bộ coi thi không giải thích gì thêm)
            </div>
        </div>
    </div>
</body>
</html>
"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route([
        '/educational_system/download_answer_sheet/<int:batch_id>',
        '/educational_system/download_answer_sheet'
    ], type='http', auth='user')
    def download_answer_sheet(self, batch_id=0, session_id=None, mode='blank', **kwargs):
        """
        Tải về trực tiếp file PDF Phiếu Trả Lời Trắc Nghiệm Chuẩn OMR (50 câu - Khổ A4).
        """
        batch = None
        if batch_id:
            batch = request.env['exam.batch'].browse(batch_id)
            if not batch.exists():
                batch = None

        session = None
        if session_id:
            session = request.env['exam.session'].browse(int(session_id))
            if not session.exists():
                session = None

        from ..utils.omr_engine import generate_omr_pdf
        pdf_content = generate_omr_pdf(batch=batch, session=session, mode=mode, total_questions=50)

        filename = "Phieu_Tra_Loi_Trac_Nghiem_OMR_50_Cau.pdf"
        if batch and mode != 'blank':
            clean_bname = re.sub(r'[^\w\-]', '_', batch.name or '')
            filename = f"Phieu_Tra_Loi_OMR_{clean_bname}.pdf"

        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ]
        )

    @http.route('/educational_system/download_batch_sample_rar/<int:batch_id>', type='http', auth='user')
    def download_batch_sample_rar(self, batch_id, **kwargs):
        """
        Tạo và tải về trực tiếp tệp nén .RAR (hoặc .ZIP) chứa toàn bộ ảnh Phiếu Trả Lời Trắc Nghiệm OMR 50 Câu
        đã tô đen sẵn SBD 6 chữ số, Mã đề 6 chữ số và phương án trả lời cho tất cả học sinh trong đợt kiểm tra.
        Giúp giáo viên / quản trị viên kiểm thử ngay luồng tải file .RAR lên hệ thống để chấm hàng loạt.
        """
        batch = request.env['exam.batch'].browse(batch_id)
        if not batch.exists():
            return request.not_found()

        if not batch.session_ids and batch.class_id:
            batch._auto_populate_students_with_sbd()

        from ..utils.omr_engine import generate_sample_omr_sheet_bytes, create_archive_from_images

        exam = batch.exam_id
        exam_code = ''.join(ch for ch in (exam.code or '102345') if ch.isdigit()).zfill(6)[:6]
        questions = exam.question_ids.sorted(key=lambda q: q.code or str(q.id)) if exam else []

        image_tuples = []
        sessions = batch.session_ids.sorted(key=lambda s: s.sbd or s.student_code or str(s.id))
        for idx, sess in enumerate(sessions):
            sbd_6 = (sess.sbd or f"{idx + 1:06d}").strip().zfill(6)[:6]
            sample_answers = {}
            for q_idx, q in enumerate(questions, start=1):
                correct_opt = (q.correct_answer or 'A').strip().upper()
                # Tạo sự đa dạng điểm số giữa các học sinh mẫu
                if idx % 3 == 1 and q_idx in (2, 5):
                    wrong_map = {'A': 'B', 'B': 'C', 'C': 'D', 'D': 'A'}
                    sample_answers[q_idx] = wrong_map.get(correct_opt, 'A')
                elif idx % 3 == 2 and q_idx in (1, 3, 6):
                    wrong_map = {'A': 'D', 'B': 'A', 'C': 'B', 'D': 'C'}
                    sample_answers[q_idx] = wrong_map.get(correct_opt, 'B')
                else:
                    sample_answers[q_idx] = correct_opt

            img_bytes = generate_sample_omr_sheet_bytes(
                answers_dict=sample_answers,
                student_code=sbd_6,
                exam_code=exam_code,
                student_name=sess.student_id.name or '',
                class_name=batch.class_id.name or '',
                exam_name=exam.name if exam else batch.name,
            )
            clean_st_code = re.sub(r'[^\w\-]', '_', sess.student_id.code or f'HS{idx+1}')
            img_filename = f"Phieu_OMR_SBD_{sbd_6}_{clean_st_code}.png"
            image_tuples.append((img_filename, img_bytes))

        archive_bytes, ext = create_archive_from_images(image_tuples, prefer_rar=True)
        clean_bcode = re.sub(r'[^\w\-]', '_', batch.code or batch.name or f'Batch_{batch.id}')
        download_filename = f"Bai_Thi_OMR_{clean_bcode}.{ext}"
        content_type = 'application/vnd.rar' if ext == 'rar' else 'application/zip'

        return request.make_response(
            archive_bytes,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', f'attachment; filename="{download_filename}"'),
            ]
        )

    @http.route('/educational_system/print_answer_sheet/<int:batch_id>', type='http', auth='user')
    def print_answer_sheet(self, batch_id, session_id=None, **kwargs):
        """
        Render Phiếu Trả Lời Trắc Nghiệm (OMR Sheet) chuẩn Bộ GD&ĐT 50 câu (2 cột x 25 câu).
        Để trống hoàn toàn: Môn thi, ngày thi, thông tin thí sinh, SBD, Mã đề thi để học sinh tự ghi và tô.
        """
        batch = None
        batch_name = "Phiếu Trả Lời Trắc Nghiệm 50 Câu"
        if batch_id != 0:
            batch = request.env['exam.batch'].browse(batch_id)
            if batch.exists():
                batch_name = batch.name
            else:
                batch = None

        # Build SBD Grid HTML (6 columns of empty boxes and 0-9 bubbles)
        sbd_cells_html = "".join(['<div class="sbd-box">&nbsp;</div>' for _ in range(6)])
        sbd_bubbles_html = ""
        for d in range(10):
            sbd_bubbles_html += '<div class="sbd-row">'
            for _ in range(6):
                sbd_bubbles_html += f'<div class="bubble-sbd">{d}</div>'
            sbd_bubbles_html += '</div>'

        # Build Exam Code Grid HTML (6 columns of empty boxes and 0-9 bubbles for 5-6 digit code)
        code_cells_html = "".join(['<div class="code-box">&nbsp;</div>' for _ in range(6)])
        code_bubbles_html = ""
        for d in range(10):
            code_bubbles_html += '<div class="code-row">'
            for _ in range(6):
                code_bubbles_html += f'<div class="bubble-code">{d}</div>'
            code_bubbles_html += '</div>'

        # Build 2 Columns of 25 questions each (1..50)
        columns_html = ""
        for col_idx in range(2):
            q_start = col_idx * 25 + 1
            col_content = ""
            for g in range(5):
                g_start = q_start + g * 5
                group_rows = ""
                for q in range(g_start, g_start + 5):
                    group_rows += f"""
                    <div class="q-row">
                        <div class="q-num">{q:02d}</div>
                        <div class="bubble">A</div>
                        <div class="bubble">B</div>
                        <div class="bubble">C</div>
                        <div class="bubble">D</div>
                    </div>
                    """
                col_content += f'<div class="q-group">{group_rows}</div>'
            columns_html += f'<div class="ans-column">{col_content}</div>'

        sheet_html = f"""
        <div class="sheet-page">
            <!-- Corner alignment marks (Fiducial marks for Scanner) -->
            <div class="corner-mark top-left"></div>
            <div class="corner-mark top-right"></div>
            <div class="corner-mark bottom-left"></div>
            <div class="corner-mark bottom-right"></div>

            <!-- Right edge timing marks -->
            <div class="timing-marks-right">
                <div class="timing-mark"></div>
                <div class="timing-mark"></div>
                <div class="timing-mark"></div>
                <div class="timing-mark"></div>
                <div class="timing-mark"></div>
            </div>

            <!-- Bottom edge timing marks -->
            <div class="timing-marks-bottom">
                <div class="timing-mark-horiz"></div>
                <div class="timing-mark-horiz"></div>
                <div class="timing-mark-horiz"></div>
                <div class="timing-mark-horiz"></div>
            </div>

            <!-- Header Title -->
            <div class="sheet-header">
                <div class="main-title">PHIẾU TRẢ LỜI TRẮC NGHIỆM</div>
                <div class="sub-title">
                    Môn thi: <span class="dotted-val" style="min-width: 170px;">&nbsp;</span>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
                    Ngày thi: <span class="dotted-val" style="min-width: 120px;">...../...../.........</span>
                </div>
            </div>

            <!-- Top Info Table -->
            <table class="info-table">
                <tr>
                    <!-- 1. Left box: Supervisors -->
                    <td class="col-supervisors">
                        <div class="supervisor-box" style="border-bottom: 1px solid #111;">
                            <div class="sup-label">Họ tên, chữ ký<br/>của cán bộ coi thi 1</div>
                        </div>
                        <div class="supervisor-box">
                            <div class="sup-label">Họ tên, chữ ký<br/>của cán bộ coi thi 2</div>
                        </div>
                    </td>

                    <!-- 2. Middle box: Candidate details (để trống 100% cho thí sinh tự điền) -->
                    <td class="col-candidate">
                        <div class="cand-row">1. Hội đồng thi: <span class="dotted-fill" style="min-width: 250px;">&nbsp;</span></div>
                        <div class="cand-row">2. Điểm thi: <span class="dotted-fill" style="min-width: 250px;">&nbsp;</span></div>
                        <div class="cand-row">3. Phòng thi số: <span class="dotted-fill" style="min-width: 250px;">&nbsp;</span></div>
                        <div class="cand-row">4. Họ và tên thí sinh: <span class="dotted-fill" style="min-width: 250px;">&nbsp;</span></div>
                        <div class="cand-row">5. Ngày sinh: <span class="dotted-fill">...../...../.........</span> &nbsp;&nbsp;&nbsp;&nbsp; (Nam/ Nữ): .............</div>
                        <div class="cand-row">6. Chữ ký của thí sinh: <span class="dotted-fill" style="min-width: 200px;">&nbsp;</span></div>
                    </td>

                    <!-- 3. Right box: SBD & Mã đề thi (để trống ô số và các bong bóng tròn) -->
                    <td class="col-grids">
                        <div class="grids-wrapper">
                            <!-- 7. Số báo danh -->
                            <div class="grid-section">
                                <div class="section-title">7. Số báo danh</div>
                                <div class="digit-boxes">
                                    {sbd_cells_html}
                                </div>
                                <div class="bubbles-matrix">
                                    {sbd_bubbles_html}
                                </div>
                            </div>

                            <!-- 8. Mã đề thi -->
                            <div class="grid-section">
                                <div class="section-title">8. Mã đề thi</div>
                                <div class="digit-boxes">
                                    {code_cells_html}
                                </div>
                                <div class="bubbles-matrix">
                                    {code_bubbles_html}
                                </div>
                            </div>
                        </div>
                    </td>
                </tr>
            </table>

            <!-- Instructions box -->
            <div class="notes-container">
                <div class="note-line">
                    <strong>Thí sinh lưu ý:</strong> - Giữ cho phiếu phẳng; không bôi bẩn, làm rách.
                </div>
                <div class="note-sub">
                    - Phải ghi đầy đủ các mục theo hướng dẫn.<br/>
                    - Số báo danh ở mục 7 là 6 chữ số cuối.<br/>
                    - Dùng bút chì đen tô kín các ô tròn tương ứng Số báo danh, Mã đề thi trong mục 7, 8.
                </div>
                <div class="note-line" style="margin-top: 2px;">
                    <strong>Phần trả lời (50 câu):</strong> Số thứ tự câu trả lời dưới đây ứng với số thứ tự câu trắc nghiệm trong đề thi. Đối với mỗi câu trắc nghiệm, thí sinh chọn và <strong>tô kín một ô tròn</strong> tương ứng với phương án trả lời.
                </div>
            </div>

            <!-- 50 Questions Answer Area (2 Columns) -->
            <div class="answers-container">
                {columns_html}
            </div>
        </div>
        """

        html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8"/>
    <title>Phiếu Trả Lời Trắc Nghiệm 50 Câu - {batch_name}</title>
    <style>
        @page {{
            size: A4 portrait;
            margin: 0;
        }}
        * {{
            box-sizing: border-box;
            font-family: "Times New Roman", Times, serif;
            color: #111;
        }}
        body {{
            margin: 0;
            padding: 0;
            background: #e9ecef;
        }}
        .no-print-bar {{
            background: #1B365D;
            color: white;
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 999;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }}
        .btn-action {{
            background: #28a745;
            color: white;
            border: none;
            padding: 8px 18px;
            font-size: 14px;
            font-weight: bold;
            border-radius: 4px;
            cursor: pointer;
            margin-left: 8px;
            text-decoration: none;
            display: inline-block;
        }}
        .btn-action:hover {{
            background: #218838;
        }}
        .sheet-page {{
            width: 210mm;
            height: 297mm;
            max-height: 297mm;
            padding: 6mm 10mm;
            margin: 15px auto;
            background: white;
            position: relative;
            box-shadow: 0 4px 15px rgba(0,0,0,0.15);
            overflow: hidden;
            page-break-inside: avoid;
            page-break-after: avoid;
        }}
        @media print {{
            html, body {{
                width: 210mm !important;
                height: 297mm !important;
                margin: 0 !important;
                padding: 0 !important;
                background: white !important;
                overflow: hidden !important;
            }}
            .no-print-bar {{
                display: none !important;
            }}
            .sheet-page {{
                margin: 0 !important;
                box-shadow: none !important;
                width: 210mm !important;
                height: 297mm !important;
                max-height: 297mm !important;
                padding: 6mm 10mm !important;
                page-break-inside: avoid !important;
                page-break-after: avoid !important;
                overflow: hidden !important;
            }}
        }}

        /* Corner Fiducials (Black Alignment Markers for OMR Scanners) */
        .corner-mark {{
            position: absolute;
            background: #000;
            width: 14px;
            height: 8px;
        }}
        .corner-mark.top-left {{
            top: 10mm;
            left: 10mm;
        }}
        .corner-mark.top-right {{
            top: 10mm;
            right: 10mm;
        }}
        .corner-mark.bottom-left {{
            bottom: 10mm;
            left: 10mm;
        }}
        .corner-mark.bottom-right {{
            bottom: 10mm;
            right: 10mm;
        }}

        /* Timing Marks */
        .timing-marks-right {{
            position: absolute;
            right: 4mm;
            top: 110mm;
            display: flex;
            flex-direction: column;
            gap: 27mm;
        }}
        .timing-mark {{
            width: 10px;
            height: 6px;
            background: #000;
        }}
        .timing-marks-bottom {{
            position: absolute;
            bottom: 4mm;
            left: 50mm;
            display: flex;
            gap: 32mm;
        }}
        .timing-mark-horiz {{
            width: 14px;
            height: 5px;
            background: #000;
        }}

        /* Header */
        .sheet-header {{
            text-align: center;
            margin-top: 2px;
            margin-bottom: 5px;
        }}
        .main-title {{
            font-size: 19px;
            font-weight: bold;
            letter-spacing: 1.5px;
            color: #0b2240;
        }}
        .sub-title {{
            font-size: 12.5px;
            margin-top: 2px;
        }}
        .dotted-val {{
            display: inline-block;
            border-bottom: 1px dotted #222;
            padding: 0 4px;
            font-weight: bold;
        }}

        /* Top Table */
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            border: 1.5px solid #111;
            margin-bottom: 4px;
        }}
        .col-supervisors {{
            width: 22%;
            vertical-align: top;
            border-right: 1px solid #111;
            padding: 0;
        }}
        .supervisor-box {{
            height: 63px;
            padding: 4px;
            text-align: center;
            display: flex;
            align-items: flex-start;
            justify-content: center;
        }}
        .sup-label {{
            font-size: 10px;
            line-height: 1.3;
        }}
        .col-candidate {{
            width: 40%;
            vertical-align: top;
            border-right: 1px solid #111;
            padding: 5px 7px;
            font-size: 11px;
            line-height: 1.85;
        }}
        .cand-row {{
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .dotted-fill {{
            border-bottom: 1px dotted #333;
            display: inline-block;
            min-width: 130px;
        }}
        .col-grids {{
            width: 38%;
            vertical-align: top;
            padding: 3px 5px;
        }}
        .grids-wrapper {{
            display: flex;
            gap: 8px;
        }}
        .grid-section {{
            flex: 1;
        }}
        .section-title {{
            font-size: 10.5px;
            font-weight: bold;
            margin-bottom: 2px;
        }}
        .digit-boxes {{
            display: flex;
            gap: 2px;
            margin-bottom: 3px;
        }}
        .sbd-box, .code-box {{
            flex: 1;
            height: 16px;
            border: 1px solid #222;
            font-size: 10px;
            font-weight: bold;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #fff;
        }}
        .bubbles-matrix {{
            display: flex;
            flex-direction: column;
            gap: 1.5px;
        }}
        .sbd-row, .code-row {{
            display: flex;
            gap: 2px;
        }}
        .bubble-sbd, .bubble-code {{
            flex: 1;
            height: 12px;
            border: 1px solid #333;
            border-radius: 50%;
            font-size: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #333;
            background: #fff;
        }}
        .bubble-sbd.shaded, .bubble-code.shaded {{
            background: #000 !important;
            color: #fff !important;
        }}

        /* Notes */
        .notes-container {{
            font-size: 9.5px;
            line-height: 1.35;
            margin-bottom: 5px;
            padding: 0 2px;
        }}
        .note-sub {{
            padding-left: 20px;
        }}

        /* Answers Container (2 Columns for 50 Questions) */
        .answers-container {{
            display: flex;
            gap: 12px;
            border: 1px solid #333;
            background: #fdfdfd;
            padding: 4px 8px;
        }}
        .ans-column {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .q-group {{
            border: 1px solid #666;
            padding: 2px 6px;
            background: #fff;
        }}
        .q-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 16px;
            padding: 0 4px;
        }}
        .q-num {{
            font-size: 10px;
            font-weight: bold;
            width: 20px;
            text-align: right;
            padding-right: 4px;
        }}
        .bubble {{
            width: 14px;
            height: 14px;
            border: 1px solid #222;
            border-radius: 50%;
            font-size: 8px;
            font-weight: bold;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #222;
            background: #fff;
        }}
    </style>
</head>
<body>
    <div class="no-print-bar">
        <div>
            <strong>Phiếu Trả Lời Trắc Nghiệm Chuẩn OMR (Khổ A4 - 50 Câu)</strong> - {batch_name}
        </div>
        <div>
            <a href="/web#id={batch_id}&model=exam.batch&view_type=form" class="btn-action" style="background: #6c757d;">Quay Lại</a>
            <a href="/educational_system/download_answer_sheet/{batch_id}?mode=blank" class="btn-action" style="background: #007bff;">📥 Tải File PDF (50 Câu)</a>
            <button class="btn-action" onclick="window.print()">🖨️ In Phiếu Ngay (Print)</button>
        </div>
    </div>

    {sheet_html}
</body>
</html>
"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])

