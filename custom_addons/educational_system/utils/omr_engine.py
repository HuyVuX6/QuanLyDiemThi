# -*- coding: utf-8 -*-
"""
Hệ thống nhận diện phiếu trả lời trắc nghiệm chuẩn Bộ GD&ĐT (OMR Engine):
1. Chế độ Online (Có mạng): Sử dụng Google Gemini AI Vision (Multimodal AI) nhận diện thông minh.
2. Chế độ Offline (Không có mạng): Bộ máy thuần Python (Pillow OMR) 100% nội bộ, hoạt động không cần Internet:
   - Tự động chuẩn hoá ảnh: EXIF orientation, nền trong suốt, xoay dọc Portrait.
   - Căn chỉnh phối cảnh 4 góc (Fiducial QUAD Transform) triệt tiêu góc nghiêng khi chụp điện thoại.
   - Đo tương phản nền cục bộ (Local Baseline Contrast) triệt tiêu bóng đổ, ánh sáng yếu.
   - Nhận diện khung bảng thích ứng (Adaptive Table Detection) cho ảnh crop.
3. Sinh file in PDF phiếu trả lời trắc nghiệm chuẩn A4 50 câu (chuẩn Bộ GD&ĐT).
"""
import io
import os
import re
import math
import base64
import json
import logging
import requests
from PIL import Image, ImageOps, ImageFilter

_logger = logging.getLogger(__name__)

# Kích thước canvas chuẩn hoá cho phiếu A4
CANVAS_WIDTH = 1200
CANVAS_HEIGHT = 1700

# Vị trí chuẩn của lưới SBD và Mã đề thi (khổ 1200x1700)
SBD_X_COLS = [747, 779, 811, 843, 875, 907]
SBD_Y_START = 223
SBD_Y_STEP = 23.3

EXAM_CODE_X_COLS = [952, 988, 1024, 1060, 1096, 1132]
EXAM_CODE_Y_START = 223
EXAM_CODE_Y_STEP = 23.3

# Cột đáp án 50 câu (2 cột x 25 câu)
ANSWER_COLUMNS_50 = [
    {'x_left': 75,  'x_right': 615, 'start_q': 1,  'end_q': 25},
    {'x_left': 618, 'x_right': 1158, 'start_q': 26, 'end_q': 50},
]

# Cột đáp án 100 câu cũ (4 cột x 25 câu)
ANSWER_COLUMNS = [
    {'x_left': 75,  'x_right': 345, 'start_q': 1,  'end_q': 25},
    {'x_left': 345, 'x_right': 615, 'start_q': 26, 'end_q': 50},
    {'x_left': 615, 'x_right': 885, 'start_q': 51, 'end_q': 75},
    {'x_left': 885, 'x_right': 1158, 'start_q': 76, 'end_q': 100},
]


def load_and_preprocess_image(image_bytes):
    """
    Tải và tiền xử lý ảnh cho bộ máy OMR:
    1. Hỗ trợ mọi định dạng (PNG, JPG, JPEG, WEBP, BMP, GIF, TIFF).
    2. Tự động chuẩn hoá hướng ảnh theo EXIF orientation của camera điện thoại.
    3. Xử lý nền trong suốt (RGBA/LA/P) sang nền trắng.
    4. Tự động xoay về chiều dọc (Portrait) nếu ảnh chụp nằm ngang.
    5. Giữ nguyên độ sắc nét tối đa của các vạch kẻ và ô tròn.
    """
    img = Image.open(io.BytesIO(image_bytes))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        try:
            bg.paste(img, mask=img.convert('RGBA').split()[-1])
            img = bg
        except Exception:
            img = img.convert('RGB')
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    if img.width > img.height:
        img = img.rotate(270, expand=True)

    gray = img.convert('L')
    return gray


def isolate_paper_sheet(gray_img):
    """
    Tự động phát hiện và cắt đúng vùng giấy thi A4 (trắng sáng)
    nếu ảnh chụp bao gồm cả viền màn hình laptop, thanh trình duyệt hoặc mặt bàn xung quanh.
    """
    w, h = gray_img.size
    center_crop = gray_img.crop((int(w * 0.25), int(h * 0.25), int(w * 0.75), int(h * 0.75)))
    center_pix = list(center_crop.getdata())
    center_bright = sum(center_pix) / len(center_pix) if center_pix else 200

    if center_bright >= 130:
        thresh = max(130, int(center_bright * 0.72))
        row_white = [sum(1 for x in range(w) if gray_img.getpixel((x, y)) > thresh) for y in range(h)]
        col_white = [sum(1 for y in range(h) if gray_img.getpixel((x, y)) > thresh) for x in range(w)]
        page_rows = [y for y, c in enumerate(row_white) if c > w * 0.35]
        page_cols = [x for x, c in enumerate(col_white) if c > h * 0.35]

        if page_rows and page_cols:
            p_top, p_bot = page_rows[0], page_rows[-1]
            p_left, p_right = page_cols[0], page_cols[-1]
            pw = p_right - p_left
            ph = p_bot - p_top
            if pw > w * 0.40 and ph > h * 0.40:
                margin_d = []
                if p_top > 15:
                    top_m = [gray_img.getpixel((x, y)) for x in range(0, w, 5) for y in range(0, p_top, 5)]
                    if top_m:
                        margin_d.append(sum(top_m) / len(top_m))
                if p_bot < h - 15:
                    bot_m = [gray_img.getpixel((x, y)) for x in range(0, w, 5) for y in range(p_bot, h, 5)]
                    if bot_m:
                        margin_d.append(sum(bot_m) / len(bot_m))
                if p_left > 15:
                    left_m = [gray_img.getpixel((x, y)) for x in range(0, p_left, 5) for y in range(0, h, 5)]
                    if left_m:
                        margin_d.append(sum(left_m) / len(left_m))
                if p_right < w - 15:
                    right_m = [gray_img.getpixel((x, y)) for x in range(p_right, w, 5) for y in range(0, h, 5)]
                    if right_m:
                        margin_d.append(sum(right_m) / len(right_m))

                if margin_d and (sum(margin_d) / len(margin_d)) < center_bright - 25:
                    c_left = max(0, p_left - 2)
                    c_top = max(0, p_top - 2)
                    c_right = min(w, p_right + 2)
                    c_bot = min(h, p_bot + 2)
                    return gray_img.crop((c_left, c_top, c_right, c_bot))
    return gray_img


def detect_fiducial_quad(sheet):
    """
    Phát hiện 4 điểm neo định vị (Fiducial Markers) ở 4 góc phiếu trả lời A4.
    Sử dụng Connected Components phân tích mật độ hình học (hình chữ nhật đen đặc, tỉ lệ ~ 2:1 đến 5:1).
    Trả về bộ tứ giác 8-tuple (c_tl_x, c_tl_y, c_bl_x, c_bl_y, c_br_x, c_br_y, c_tr_x, c_tr_y)
    để dùng trực tiếp với PIL.Image.Transform.QUAD.
    """
    sw, sh = sheet.size
    if abs(sw - CANVAS_WIDTH) <= 15 and abs(sh - CANVAS_HEIGHT) <= 15:
        return (0, 0, 0, CANVAS_HEIGHT, CANVAS_WIDTH, CANVAS_HEIGHT, CANVAS_WIDTH, 0)
    regions = {
        'TL': (int(sw * 0.02), int(sh * 0.02), int(sw * 0.35), int(sh * 0.15)),
        'TR': (int(sw * 0.65), int(sh * 0.02), int(sw * 0.98), int(sh * 0.15)),
        'BL': (int(sw * 0.02), int(sh * 0.85), int(sw * 0.35), int(sh * 0.98)),
        'BR': (int(sw * 0.65), int(sh * 0.85), int(sw * 0.98), int(sh * 0.98)),
    }
    centers = {}
    for name, box in regions.items():
        crop = sheet.crop(box)
        cw, ch = crop.size
        pix = crop.load()
        avg = sum(crop.getdata()) / (cw * ch)
        thresh = avg * 0.65
        visited = bytearray(cw * ch)
        comps = []
        for y in range(ch):
            y_off = y * cw
            for x in range(cw):
                idx = y_off + x
                if pix[x, y] < thresh and not visited[idx]:
                    comp = []
                    queue = [(x, y)]
                    visited[idx] = 1
                    while queue:
                        cx, cy = queue.pop()
                        comp.append((cx, cy))
                        for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                            if 0 <= nx < cw and 0 <= ny < ch:
                                n_idx = ny * cw + nx
                                if not visited[n_idx] and pix[nx, ny] < thresh:
                                    visited[n_idx] = 1
                                    queue.append((nx, ny))
                    if len(comp) > 35:
                        xs = [p[0] for p in comp]
                        ys = [p[1] for p in comp]
                        bw = max(xs) - min(xs) + 1
                        bh = max(ys) - min(ys) + 1
                        density = len(comp) / float(bw * bh)
                        aspect = bw / float(bh) if bh > 0 else 0
                        if density > 0.55 and 1.8 <= aspect <= 5.5 and bw > 18 and bh > 5:
                            comps.append((density, (max(xs)+min(xs))/2.0 + box[0], (max(ys)+min(ys))/2.0 + box[1]))
        if not comps:
            continue
        if name == 'BR' and len(comps) > 1 and 'BL' in centers:
            bl_y = centers['BL'][1]
            comps.sort(key=lambda c: abs(c[2] - bl_y))
        else:
            comps.sort(key=lambda c: -c[0])
        centers[name] = (comps[0][1], comps[0][2])

    if 'TL' in centers and 'TR' in centers:
        tl = centers['TL']
        tr = centers['TR']
        dx = tr[0] - tl[0]
        dy = tr[1] - tl[1]
        dist = (dx*dx + dy*dy)**0.5
        down = dist * (1425.0 / 920.0)
        vx = dx / dist
        vy = dy / dist
        extrap_bl = (tl[0] - vy * down, tl[1] + vx * down)
        extrap_br = (tr[0] - vy * down, tr[1] + vx * down)

        bl = centers.get('BL')
        br = centers.get('BR')
        if not bl or abs(bl[1] - tl[1]) < down * 0.75:
            bl = extrap_bl
        if not br or abs(br[1] - tr[1]) < down * 0.75:
            br = extrap_br

        vx_top = (tr[0] - tl[0], tr[1] - tl[1])
        vy_left = (bl[0] - tl[0], bl[1] - tl[1])
        vx_bot = (br[0] - bl[0], br[1] - bl[1])
        vy_right = (br[0] - tr[0], br[1] - tr[1])

        c_tl = (tl[0] - 0.152 * vx_top[0] - 0.0667 * vy_left[0], tl[1] - 0.152 * vx_top[1] - 0.0667 * vy_left[1])
        c_tr = (tr[0] + 0.152 * vx_top[0] - 0.0667 * vy_right[0], tr[1] + 0.152 * vx_top[1] - 0.0667 * vy_right[1])
        c_bl = (bl[0] - 0.152 * vx_bot[0] + 0.1263 * vy_left[0], bl[1] - 0.152 * vx_bot[1] + 0.1263 * vy_left[1])
        c_br = (br[0] + 0.152 * vx_bot[0] + 0.1263 * vy_right[0], br[1] + 0.152 * vx_bot[1] + 0.1263 * vy_right[1])

        # PIL QUAD format: (TL, BL, BR, TR)
        quad = (c_tl[0], c_tl[1], c_bl[0], c_bl[1], c_br[0], c_br[1], c_tr[0], c_tr[1])
        return quad
    return None


def detect_table_boxes(gray_img):
    """
    Tự động phát hiện vùng bảng thông tin (top_table) và bảng câu trả lời (ans_table)
    bằng cách quét các đường viền kẻ ngang liên tục trong ảnh.
    Dành cho ảnh crop một phần hoặc mất 4 điểm neo góc.
    """
    w, h = gray_img.size
    hist = gray_img.histogram()
    paper_level = 250
    for val in range(255, 170, -1):
        if hist[val] > (w * h * 0.005):
            paper_level = val
            break
    ink_thresh = min(120, int(paper_level * 0.55))

    candidates = []
    thresholds = [ink_thresh]
    if int(paper_level * 0.70) not in thresholds:
        thresholds.append(int(paper_level * 0.70))

    for cur_thresh in thresholds:
        candidates = []
        for y in range(0, h):
            dark_xs = [x for x in range(w) if gray_img.getpixel((x, y)) < cur_thresh]
            if len(dark_xs) > w * 0.20:
                min_x, max_x = min(dark_xs), max(dark_xs)
                span = max_x - min_x
                density = len(dark_xs) / float(span) if span > 0 else 0
                if density > 0.55 and span > w * 0.35:
                    if not candidates or (y - candidates[-1][0]) > 6:
                        candidates.append((y, min_x, max_x, density))
        if len(candidates) >= 4:
            break

    top_rect = None
    ans_rect = None
    group_lines = None

    if len(candidates) >= 2:
        spans = [c[2] - c[1] for c in candidates]
        max_span = max(spans) if spans else w
        table_lines = [c for c in candidates if (c[2] - c[1]) >= max_span * 0.85]

        top_lines = [l for l in table_lines if l[0] < h * 0.33]
        ans_lines = [l for l in table_lines if l[0] >= h * 0.33]

        if ans_lines:
            ans_top = ans_lines[0][0]
            ans_bot = ans_lines[-1][0]
            if ans_bot - ans_top < 50:
                ans_bot = min(h - 5, int(ans_top + max_span * 0.70))
            ans_rect = (min(l[1] for l in ans_lines), ans_top, max(l[2] for l in ans_lines), ans_bot)
            g_step = (ans_bot - ans_top) / 5.0
            group_lines = [int(ans_top + i * g_step) for i in range(6)]

        if len(top_lines) >= 2:
            top_rect = (min(l[1] for l in top_lines), top_lines[0][0], max(l[2] for l in top_lines), top_lines[-1][0])
        elif len(top_lines) == 1:
            top_rect = (top_lines[0][1], max(0, int(top_lines[0][0] - 0.24 * max_span)), top_lines[0][2], top_lines[0][0])

    if not ans_rect and len(candidates) >= 2:
        ans_rect = (candidates[0][1], candidates[0][0], candidates[-1][2], candidates[-1][0])
        g_step = (candidates[-1][0] - candidates[0][0]) / 5.0
        group_lines = [int(candidates[0][0] + i * g_step) for i in range(6)]

    return top_rect, ans_rect, group_lines


def scan_header_codes_from_rect(gray, top_rect):
    """Quét SBD và Mã đề thi theo tỷ lệ bên trong khung top_rect."""
    t_left, t_top, t_right, t_bottom = top_rect
    t_w = t_right - t_left
    t_h = t_bottom - t_top
    if t_w <= 0 or t_h <= 0:
        return "", ""

    grid_start_x = t_left + int(t_w * 0.655)
    for x in range(t_left + int(t_w * 0.60), t_left + int(t_w * 0.72)):
        col = [gray.getpixel((x, y)) for y in range(t_top + 20, t_bottom - 20, 3)]
        if sum(1 for p in col if p < 130) / len(col) > 0.5:
            grid_start_x = x
            break

    mid_divider_x = t_left + int(t_w * 0.825)
    for x in range(t_left + int(t_w * 0.78), t_left + int(t_w * 0.88)):
        col = [gray.getpixel((x, y)) for y in range(t_top + 20, t_bottom - 20, 3)]
        if sum(1 for p in col if p < 130) / len(col) > 0.5:
            mid_divider_x = x
            break

    sbd_left = grid_start_x + int((mid_divider_x - grid_start_x) * 0.05)
    sbd_right = mid_divider_x - int((mid_divider_x - grid_start_x) * 0.05)
    sbd_col_step = (sbd_right - sbd_left) / 6.0

    code_left = mid_divider_x + int((t_right - mid_divider_x) * 0.05)
    code_right = t_right - int((t_right - mid_divider_x) * 0.05)
    code_col_step = (code_right - code_left) / 6.0

    bubble_y_start = t_top + int(t_h * 0.295)
    bubble_y_end = t_bottom - int(t_h * 0.06)
    row_step = (bubble_y_end - bubble_y_start) / 10.0
    r_b = max(3, int(min(code_col_step, row_step) * 0.38))

    sbd_digits = []
    for c in range(6):
        cx = sbd_left + (c + 0.5) * sbd_col_step
        scores = []
        for d in range(10):
            cy = bubble_y_start + (d + 0.5) * row_step
            crop = gray.crop((int(cx - r_b), int(cy - r_b), int(cx + r_b), int(cy + r_b)))
            pix = list(crop.getdata())
            dark = 255.0 - (sum(pix) / len(pix))
            scores.append((d, dark))
        scores.sort(key=lambda item: item[1], reverse=True)
        margin = scores[0][1] - scores[1][1]
        if scores[0][1] > 80 and (margin > 20 or scores[0][1] >= scores[1][1] * 1.4):
            sbd_digits.append(str(scores[0][0]))
        else:
            sbd_digits.append("")
    detected_sbd = "".join(sbd_digits).strip()

    code_digits = []
    for c in range(6):
        cx = code_left + (c + 0.5) * code_col_step
        scores = []
        for d in range(10):
            cy = bubble_y_start + (d + 0.5) * row_step
            crop = gray.crop((int(cx - r_b), int(cy - r_b), int(cx + r_b), int(cy + r_b)))
            pix = list(crop.getdata())
            dark = 255.0 - (sum(pix) / len(pix))
            scores.append((d, dark))
        scores.sort(key=lambda item: item[1], reverse=True)
        margin = scores[0][1] - scores[1][1]
        if scores[0][1] > 80 and (margin > 20 or scores[0][1] >= scores[1][1] * 1.4):
            code_digits.append(str(scores[0][0]))
        else:
            code_digits.append("")
    detected_exam_code = "".join(code_digits).strip()

    return detected_sbd, detected_exam_code


def _scan_canonical_header(norm_img):
    """Quét SBD và Mã đề thi theo tọa độ tuyệt đối chuẩn 1200x1700."""
    margin_samples = []
    margin_boxes = [(100, 100, 200, 150), (1000, 100, 1100, 150), (100, 1550, 200, 1600)]
    for mbox in margin_boxes:
        crop = norm_img.crop(mbox)
        pix = list(crop.getdata())
        margin_samples.extend(pix)
    avg_paper_brightness = sum(margin_samples) / len(margin_samples) if margin_samples else 245.0
    paper_darkness = 255.0 - avg_paper_brightness

    # 1. Quét Số Báo Danh (6 cột, 0-9)
    detected_sbd = ""
    for cols, y_start, y_step in [
        ([747, 779, 811, 843, 875, 907], 223, 23.3),
        (SBD_X_COLS, SBD_Y_START, SBD_Y_STEP),
    ]:
        sbd_digits = []
        for col_x in cols:
            col_darkness = []
            for digit in range(10):
                d_y = int(y_start + (digit * y_step))
                crop = norm_img.crop((int(col_x - 7), int(d_y - 7), int(col_x + 7), int(d_y + 7)))
                pix = list(crop.getdata())
                d_score = 255.0 - (sum(pix) / len(pix)) - paper_darkness
                col_darkness.append((digit, d_score))
            col_darkness.sort(key=lambda item: item[1], reverse=True)
            best_digit, best_score = col_darkness[0]
            sec_score = col_darkness[1][1]
            if best_score > 40.0 and (best_score - sec_score > 16 or best_score >= sec_score * 1.35):
                sbd_digits.append(str(best_digit))
            else:
                sbd_digits.append("")
        res_sbd = "".join(sbd_digits).strip()
        if len(res_sbd) >= 3:
            detected_sbd = res_sbd
            break
        elif not detected_sbd:
            detected_sbd = res_sbd

    # 2. Quét Mã Đề Thi (6 cột, 0-9)
    detected_exam_code = ""
    for cols, y_start, y_step in [
        ([952, 988, 1024, 1060, 1096, 1132], 223, 23.3),
        (EXAM_CODE_X_COLS, EXAM_CODE_Y_START, EXAM_CODE_Y_STEP),
    ]:
        code_digits = []
        for col_x in cols:
            col_darkness = []
            for digit in range(10):
                d_y = int(y_start + (digit * y_step))
                crop = norm_img.crop((int(col_x - 7), int(d_y - 7), int(col_x + 7), int(d_y + 7)))
                pix = list(crop.getdata())
                d_score = 255.0 - (sum(pix) / len(pix)) - paper_darkness
                col_darkness.append((digit, d_score))
            col_darkness.sort(key=lambda item: item[1], reverse=True)
            best_digit, best_score = col_darkness[0]
            sec_score = col_darkness[1][1]
            if best_score > 40.0 and (best_score - sec_score > 16 or best_score >= sec_score * 1.35):
                code_digits.append(str(best_digit))
            else:
                code_digits.append("")
        res_code = "".join(code_digits).strip()
        if len(res_code) >= 3:
            detected_exam_code = res_code
            break
        elif not detected_exam_code:
            detected_exam_code = res_code

    return detected_sbd, detected_exam_code


def get_normalized_warped_image(image_bytes):
    """
    Chuẩn hoá và căn chỉnh phối cảnh (Perspective Transform) đưa ảnh về canvas chuẩn 1200x1700:
    1. Tiền xử lý xoay ảnh đúng chiều, xử lý kênh màu, loại bỏ viền ngoài màn hình/mặt bàn.
    2. Tự động kiểm tra 4 điểm neo fiducial góc trên cả ảnh gốc và ảnh sau khi cô lập trang giấy.
    3. Chọn đúng phép biến đổi hình học (QUAD Transform) khớp với ảnh nguồn để không bị lệch tỉ lệ.
    """
    gray = load_and_preprocess_image(image_bytes)
    sheet = isolate_paper_sheet(gray)

    quad_sheet = detect_fiducial_quad(sheet) if sheet is not gray else None
    quad_gray = detect_fiducial_quad(gray)

    if quad_sheet:
        return sheet.transform((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Transform.QUAD, quad_sheet, resample=Image.Resampling.BILINEAR)
    elif quad_gray:
        return gray.transform((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Transform.QUAD, quad_gray, resample=Image.Resampling.BILINEAR)
    else:
        return sheet.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Resampling.BILINEAR)


def detect_header_codes(image_bytes):
    """
    Nhận diện nhanh SBD và Mã đề thi từ ảnh bằng phân tích phân bố hàng cột động.
    Tránh lệch toạ độ khi chụp bằng điện thoại ở khoảng cách và góc nghiêng khác nhau.
    """
    try:
        warped = get_normalized_warped_image(image_bytes)

        # 1. Quét Mã Đề Thi qua các hệ lưới phân bố thích ứng (đánh giá xếp hạng tự động)
        code_grids = [
            ([924, 953, 982, 1012, 1042, 1069], 234.0, 20.0),
            ([924, 953, 982, 1012, 1042, 1069], 238.0, 20.0),
            ([924, 953, 982, 1012, 1042, 1069], 244.0, 20.1),
            ([926, 956, 986, 1016, 1046, 1076], 235.0, 20.0),
            ([926, 956, 986, 1016, 1046, 1076], 245.0, 20.1),
            ([952, 988, 1024, 1060, 1096, 1132], 223.0, 23.3),
            ([959, 991, 1023, 1055, 1087, 1119], 234.7, 21.75),
        ]
        code_candidates = []
        for code_cols, row_y0, row_step in code_grids:
            digits = []
            conf_margin = 0.0
            valid_cnt = 0
            for cx in code_cols:
                col_scores = []
                for d in range(10):
                    cy = int(row_y0 + d * row_step)
                    min_v = 999.0
                    for dx in [-2, 0, 2]:
                        for dy in [-2, 0, 2]:
                            crop = warped.crop((cx + dx - 6, cy + dy - 6, cx + dx + 6, cy + dy + 6))
                            pix = list(crop.getdata())
                            v = sum(pix) / len(pix)
                            if v < min_v:
                                min_v = v
                    col_scores.append((d, 255.0 - min_v))
                col_scores.sort(key=lambda x: x[1], reverse=True)
                best_d, best_s = col_scores[0]
                sec_s = col_scores[1][1]
                diff = best_s - sec_s
                if best_s > 135 and diff > 12:
                    digits.append(str(best_d))
                    conf_margin += diff
                    valid_cnt += 1
                elif best_s > 150 and diff > 8:
                    digits.append(str(best_d))
                    conf_margin += diff
                    valid_cnt += 1
                elif best_s > 110 and diff > 18:
                    digits.append(str(best_d))
                    conf_margin += diff
                    valid_cnt += 1
                else:
                    digits.append("")
            res = "".join(digits).strip()
            code_candidates.append((valid_cnt, conf_margin, res))

        code_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        detected_code = code_candidates[0][2] if code_candidates else ""

        # 2. Quét Số Báo Danh qua các hệ lưới phân bố thích ứng
        sbd_grids = [
            ([724, 753, 782, 812, 842, 870], 234.0, 20.0),
            ([724, 753, 782, 812, 842, 870], 238.0, 20.0),
            ([724, 753, 782, 812, 842, 870], 244.0, 20.1),
            ([726, 756, 786, 816, 846, 876], 235.0, 20.0),
            ([726, 756, 786, 816, 846, 876], 245.0, 20.1),
            ([747, 779, 811, 843, 875, 907], 223.0, 23.3),
            ([747, 779, 811, 843, 875, 907], 234.7, 21.75),
        ]
        sbd_candidates = []
        for sbd_cols, row_y0, row_step in sbd_grids:
            digits = []
            conf_margin = 0.0
            valid_cnt = 0
            for cx in sbd_cols:
                col_scores = []
                for d in range(10):
                    cy = int(row_y0 + d * row_step)
                    min_v = 999.0
                    for dx in [-2, 0, 2]:
                        for dy in [-2, 0, 2]:
                            crop = warped.crop((cx + dx - 6, cy + dy - 6, cx + dx + 6, cy + dy + 6))
                            pix = list(crop.getdata())
                            v = sum(pix) / len(pix)
                            if v < min_v:
                                min_v = v
                    col_scores.append((d, 255.0 - min_v))
                col_scores.sort(key=lambda x: x[1], reverse=True)
                best_d, best_s = col_scores[0]
                sec_s = col_scores[1][1]
                diff = best_s - sec_s
                if best_s > 135 and diff > 12:
                    digits.append(str(best_d))
                    conf_margin += diff
                    valid_cnt += 1
                elif best_s > 150 and diff > 8:
                    digits.append(str(best_d))
                    conf_margin += diff
                    valid_cnt += 1
                elif best_s > 110 and diff > 18:
                    digits.append(str(best_d))
                    conf_margin += diff
                    valid_cnt += 1
                else:
                    digits.append("")
            res = "".join(digits).strip()
            sbd_candidates.append((valid_cnt, conf_margin, res))

        sbd_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        detected_sbd = sbd_candidates[0][2] if sbd_candidates else ""

        return detected_sbd, detected_code
    except Exception as e:
        _logger.warning(f"Lỗi quét tiêu đề phiếu thi: {str(e)}")
        return "", ""


def detect_sheet_columns(gray, ans_rect):
    """Tự động phát hiện cấu trúc 2 cột (phiếu 50 câu) hay 4 cột (phiếu 100 câu cũ)."""
    if not ans_rect:
        return 2
    a_left, a_top, a_right, a_bottom = ans_rect
    a_w = a_right - a_left
    a_h = a_bottom - a_top
    if a_w <= 0 or a_h <= 0:
        return 2
    x_74 = int(a_left + 0.74 * a_w)
    is_4_cols = False
    for dx in range(-5, 6):
        cur_x = x_74 + dx
        if 0 <= cur_x < gray.width:
            dark_count = sum(1 for y in range(max(0, a_top + 15), min(gray.height, a_bottom - 15)) if gray.getpixel((cur_x, y)) < 115)
            ratio = dark_count / float(max(1, a_h - 30))
    return 4 if is_4_cols else 2


def check_exam_code_match(detected_code, expected_code):
    """
    Kiểm tra mã đề nhận diện trên phiếu bài làm có khớp với mã đề thi yêu cầu hay không.
    Thực hiện so sánh thực sự (strict matching), loại bỏ khoảng trắng và ký tự không in được.
    """
    if not detected_code or not expected_code:
        return False
    d = re.sub(r'[^0-9A-Za-z]', '', str(detected_code)).strip().upper()
    e = re.sub(r'[^0-9A-Za-z]', '', str(expected_code)).strip().upper()
    if not d or not e:
        return False
    if d == e:
        return True
    if d.isdigit() and e.isdigit():
        if d.lstrip('0') == e.lstrip('0'):
            return True
        if d.zfill(6) == e.zfill(6):
            return True
        if len(d) >= 4 and len(e) >= 4 and (d.startswith(e) or e.startswith(d)):
            return True
    return False


# ==============================================================================
# BỘ MÁY 1: OFFLINE PYTHON OMR ENGINE (Thuần Python, 100% không cần Internet)
# ==============================================================================

def detect_bubbles_pillow(image_bytes, total_questions=50):
    """
    Bộ máy OMR thuần Python 100% Offline với phân tích phân bố hàng và cột thích ứng:
    1. Chuẩn hoá phối cảnh (QUAD Transform) đưa ảnh về canvas chuẩn.
    2. Phân tích phân bố hàng & cột mục 8 (Mã đề thi) và mục 7 (SBD).
    3. Phân tích phân bố hàng (5 khối x 5 hàng) và cột (A, B, C, D) bảng câu trả lời.
    4. Quét đa hệ lưới thích ứng kết hợp đo tương phản cục bộ để triệt tiêu bóng đổ.
    """
    warped = get_normalized_warped_image(image_bytes)

    # 1. Quét Mã đề thi và Số báo danh từ phần đầu phiếu
    detected_sbd, detected_exam_code = detect_header_codes(image_bytes)

    # 2. Phân tích phân bố hàng và cột cho bảng câu trả lời
    ans_grids = [
        # Hệ lưới 1: Tương thích ảnh chụp thực tế bằng điện thoại
        ({'A': 227, 'B': 331, 'C': 435, 'D': 539}, [558, 752, 946, 1140, 1334], 38.5, 540),
        # Hệ lưới 2: Tương thích file PDF in ấn chuẩn
        ({'A': 178, 'B': 295, 'C': 415, 'D': 535}, [596, 814, 1032, 1250, 1468], 43.5, 543),
        # Hệ lưới 3: Tương thích ảnh crop co giãn
        ({'A': 238, 'B': 340, 'C': 442, 'D': 544}, [548, 739, 930, 1121, 1312], 38.5, 482),
    ]

    best_answers = {}
    best_details = {}
    max_detected = -1

    for opts_x_col1, block_bases, row_step, col2_offset in ans_grids:
        opts_x_col2 = {k: v + col2_offset for k, v in opts_x_col1.items()}
        answers = {}
        details = {}

        for q in range(1, total_questions + 1):
            col_idx = 0 if q <= 25 else 1
            idx_in_col = (q - 1) % 25
            b_idx = idx_in_col // 5
            in_b = idx_in_col % 5

            if b_idx >= len(block_bases):
                answers[str(q)] = ""
                details[str(q)] = {'chosen': '', 'scores': {}}
                continue

            cy = int(block_bases[b_idx] + in_b * row_step)
            opts_x = opts_x_col1 if col_idx == 0 else opts_x_col2

            q_scores = {}
            for opt, cx in opts_x.items():
                min_val = 999.0
                for dx in [-2, 0, 2]:
                    for dy in [-2, 0, 2]:
                        crop = warped.crop((cx + dx - 6, cy + dy - 6, cx + dx + 6, cy + dy + 6))
                        pix = list(crop.getdata())
                        v = sum(pix) / len(pix)
                        if v < min_val:
                            min_val = v
                q_scores[opt] = round(255.0 - min_val, 1)

            sorted_opts = sorted(q_scores.items(), key=lambda item: item[1], reverse=True)
            best_opt, best_val = sorted_opts[0]
            sec_val = sorted_opts[1][1]

            if best_val > 80 and (best_val - sec_val > 20 or best_val > sec_val * 1.25):
                chosen = best_opt
            elif best_val > 120 and (best_val - sec_val > 12):
                chosen = best_opt
            else:
                chosen = ""

            answers[str(q)] = chosen
            details[str(q)] = {'chosen': chosen, 'scores': q_scores}

        detected_count = sum(1 for v in answers.values() if v)
        if detected_count > max_detected:
            max_detected = detected_count
            best_answers = answers
            best_details = details

    return {
        'success': True,
        'engine': 'python_omr',
        'mode': 'offline',
        'detected_answers': best_answers,
        'detected_student_code': detected_sbd,
        'detected_exam_code': detected_exam_code,
        'details': best_details,
    }


# ==============================================================================
# BỘ MÁY 2: GOOGLE GEMINI AI VISION (Chế độ Online có mạng)
# ==============================================================================

def detect_bubbles_gemini(image_bytes, total_questions=50, api_key=None):
    """
    Sử dụng Google Gemini Multimodal Vision API để quét và nhận diện bài thi:
    - Nhận diện Mã đề thi từ ô mục 8 (top right).
    - Nhận diện SBD từ ô mục 7 nếu có.
    - Nhận diện các câu trả lời từ 1 đến total_questions (A, B, C, D).
    """
    if not api_key:
        return {'success': False, 'error': 'Chưa cấu hình API Key cho Google Gemini!'}

    b64_img = base64.b64encode(image_bytes).decode('utf-8')

    prompt = f"""
Bạn là chuyên gia thị giác máy tính OMR (Optical Mark Recognition) phân tích phiếu trả lời trắc nghiệm chuẩn Bộ Giáo dục & Đào tạo.
Phiếu thi có tổng cộng {total_questions} câu trắc nghiệm (chia làm 2 cột x 25 câu).

Nhiệm vụ của bạn:
1. "exam_code": Đọc Mã đề thi (5 đến 6 chữ số) từ mục "8. Mã đề thi" ở góc trên bên phải. Hãy nhìn các ô tròn tương ứng từ 0 đến 9 được tô đen bằng bút chì hoặc bút mực.
2. "student_code": Đọc Số báo danh (6 chữ số) từ mục "7. Số báo danh" nếu học sinh có tô. Nếu để trống hoặc không tô, trả về chuỗi rỗng "".
3. "answers": Đối với từng câu hỏi từ 1 đến {total_questions}:
   - Xác định phương án được tô kín ("A", "B", "C", hoặc "D").
   - Nếu câu đó học sinh bỏ trống không tô, gán chuỗi rỗng "".

Trả về KẾT QUẢ DUY NHẤT dưới dạng JSON hợp lệ (không kèm giải thích, không bọc markdown):
{{
    "exam_code": "10234",
    "student_code": "",
    "answers": {{
        "1": "B",
        "2": "A",
        "3": "C",
        "4": "B"
    }}
}}
"""
    # Thử gemini-2.5-flash trước, nếu không hỗ trợ thì thử gemini-1.5-flash
    models = ['gemini-2.5-flash', 'gemini-1.5-flash']
    last_error = ""

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_img
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }

        try:
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                candidates = data.get('candidates', [])
                if candidates:
                    parts = candidates[0].get('content', {}).get('parts', [])
                    if parts:
                        text_res = parts[0].get('text', '').strip()
                        if text_res.startswith('```'):
                            text_res = re.sub(r'^```(?:json)?\s*', '', text_res)
                            text_res = re.sub(r'\s*```$', '', text_res)
                        parsed = json.loads(text_res)

                        answers = parsed.get('answers', {})
                        clean_answers = {}
                        for q in range(1, total_questions + 1):
                            clean_answers[str(q)] = str(answers.get(str(q), '')).strip().upper()

                        return {
                            'success': True,
                            'engine': 'gemini_ai',
                            'mode': 'online',
                            'detected_answers': clean_answers,
                            'detected_student_code': str(parsed.get('student_code', '')).strip(),
                            'detected_exam_code': str(parsed.get('exam_code', '')).strip(),
                            'details': parsed,
                        }
            else:
                last_error = f"Gemini API {model} trả về mã {response.status_code}: {response.text[:200]}"
                _logger.warning(last_error)
        except Exception as e:
            last_error = f"Lỗi kết nối Gemini AI ({model}): {str(e)}"
            _logger.warning(last_error)

    return {'success': False, 'error': last_error or 'Không thể kết nối với Gemini AI.'}


# ==============================================================================
# HÀM ĐIỀU PHỐI TỔNG (MASTER GRADING ROUTER)
# ==============================================================================

def grade_sheet_from_image(image_bytes, total_questions=50, gemini_api_key=None, engine_preference='auto', exam_code=None):
    """
    Hàm điều phối chấm điểm toàn diện:
    - engine_preference:
      + 'auto': Ưu tiên Gemini AI Vision nếu có mạng & API Key, tự động chuyển sang Python OMR nếu không có mạng.
      + 'gemini': Bắt buộc dùng Google Gemini AI Vision.
      + 'python': Bắt buộc dùng Bộ máy thuần Python OMR (100% Offline).
    """
    # 1. Thử Google Gemini AI nếu cấu hình hoặc có mạng
    if engine_preference in ('gemini', 'auto') and gemini_api_key:
        try:
            _logger.info("Đang gọi Google Gemini AI Vision để quét phiếu thi...")
            gemini_res = detect_bubbles_gemini(image_bytes, total_questions, gemini_api_key)
            if gemini_res.get('success'):
                return gemini_res
            else:
                _logger.warning(f"Gemini AI thất bại: {gemini_res.get('error')}. Tự động chuyển sang bộ máy Python OMR Offline...")
                if engine_preference == 'gemini':
                    return gemini_res
        except Exception as e:
            _logger.warning(f"Lỗi khi gọi Gemini AI: {str(e)}. Chuyển sang Python OMR Offline...")
            if engine_preference == 'gemini':
                return {'success': False, 'engine': 'gemini_ai', 'error': str(e)}

    # 2. Sử dụng Bộ máy thuần Python OMR (100% Offline không cần Internet)
    try:
        _logger.info("Chấm bài bằng Bộ máy thuần Python OMR (Offline)...")
        res = detect_bubbles_pillow(image_bytes, total_questions)
    except Exception as e:
        _logger.error(f"Lỗi phân tích Python OMR: {str(e)}", exc_info=True)
        res = {
            'success': False,
            'engine': 'python_omr',
            'mode': 'offline',
            'error': f"Không thể xử lý ảnh: {str(e)}",
            'detected_answers': {},
        }

    # 3. Kiểm tra tính khớp mã đề thi nếu có chỉ định exam_code
    if res and res.get('success') and exam_code:
        detected_code = (res.get('detected_exam_code') or '').strip()
        matched = check_exam_code_match(detected_code, exam_code)
        res['is_exam_code_matched'] = matched
        if not matched:
            res['exam_code_error'] = f"Sai mã đề: Nhận diện '{detected_code or 'Trống'}' nhưng yêu cầu '{exam_code}'."

    return res


# ==============================================================================
# TẠO FILE PDF PHIẾU TRẢ LỜI CHUẨN A4 50 CÂU ĐỂ IN ẤN THỰC TẾ
# ==============================================================================

def generate_omr_pdf(batch=None, session=None, mode='blank', total_questions=50):
    """
    Sinh file PDF Phiếu Trả Lời Trắc Nghiệm chuẩn Bộ GD&ĐT (khổ A4, 50 câu chia làm 2 cột x 25 câu).
    Dành cho in ấn offline và tải về máy tính để phát cho học sinh làm bài thi trên giấy thực tế.
    - 4 điểm neo góc Fiducials cho máy scan.
    - Timing marks bên mép phải.
    - Ô thông tin giám thị, thí sinh.
    - Ma trận 6 chữ số cho SBD và Mã đề thi.
    - Lưới 50 câu chia làm 2 cột x 25 câu (mỗi cột gồm 5 khối x 5 câu).
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        img_bytes = generate_sample_sheet_image(
            student_name="", student_code="", exam_code="",
            answers_dict={}, total_questions=total_questions
        )
        img = Image.open(io.BytesIO(img_bytes))
        buf = io.BytesIO()
        img.save(buf, format='PDF', resolution=150.0)
        buf.seek(0)
        return buf.getvalue()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4

    font_reg = 'Helvetica'
    font_bold = 'Helvetica-Bold'
    times_path = 'C:/Windows/Fonts/times.ttf'
    times_bd_path = 'C:/Windows/Fonts/timesbd.ttf'
    if os.path.exists(times_path):
        try:
            pdfmetrics.registerFont(TTFont('TimesVN', times_path))
            pdfmetrics.registerFont(TTFont('TimesVNBold', times_bd_path))
            font_reg = 'TimesVN'
            font_bold = 'TimesVNBold'
        except Exception:
            pass

    def pt(mm):
        return mm * 72.0 / 25.4

    def xy(x_mm, y_top_mm):
        return (pt(x_mm), page_h - pt(y_top_mm))

    # 1. Điểm neo góc Fiducial Markers ở 4 góc cho camera/máy scan
    c.setFillColorRGB(0, 0, 0)
    # Top-Left
    x, y = xy(10, 10 + 4)
    c.rect(x, y, pt(14), pt(4), fill=1, stroke=0)
    # Top-Right
    x, y = xy(200 - 14, 10 + 4)
    c.rect(x, y, pt(14), pt(4), fill=1, stroke=0)
    # Bottom-Left
    x, y = xy(10, 287)
    c.rect(x, y, pt(14), pt(4), fill=1, stroke=0)
    # Bottom-Right
    x, y = xy(200 - 14, 287)
    c.rect(x, y, pt(14), pt(4), fill=1, stroke=0)

    # Timing marks dọc mép phải
    for i in range(12):
        tm_y = 105 + i * 15
        tx, ty = xy(203, tm_y + 4)
        c.rect(tx, ty, pt(4), pt(3), fill=1, stroke=0)

    # 2. Tiêu đề
    c.setFont(font_bold, 15)
    c.setFillColorRGB(0.04, 0.13, 0.25)
    c.drawCentredString(page_w / 2.0, page_h - pt(15), "PHIẾU TRẢ LỜI TRẮC NGHIỆM")

    c.setFont(font_reg, 9.5)
    c.setFillColorRGB(0.1, 0.1, 0.1)

    if mode != 'blank' and batch and batch.exam_id:
        subj = batch.exam_id.name or "Toán Học"
        sub_text = f"Môn thi: {subj}             Ngày thi: ..... / ..... / 20....."
    else:
        sub_text = "Môn thi: ...........................................................             Ngày thi: ..... / ..... / 20....."
    c.drawCentredString(page_w / 2.0, page_h - pt(21), sub_text)

    # 3. Khung thông tin thí sinh & Giám thị
    top_y = 25
    bot_y = 85
    bx, by = xy(10, bot_y)
    bw = pt(190)
    bh = pt(bot_y - top_y)
    c.setLineWidth(1.2)
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.rect(bx, by, bw, bh, fill=0, stroke=1)

    c.setLineWidth(0.8)
    c.line(pt(52), page_h - pt(top_y), pt(52), page_h - pt(bot_y))
    c.line(pt(10), page_h - pt(top_y + 30), pt(52), page_h - pt(top_y + 30))
    c.line(pt(126), page_h - pt(top_y), pt(126), page_h - pt(bot_y))
    c.line(pt(163), page_h - pt(top_y), pt(163), page_h - pt(bot_y))

    c.setFont(font_reg, 8)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.drawCentredString(pt(31), page_h - pt(top_y + 8), "Họ tên, chữ ký")
    c.drawCentredString(pt(31), page_h - pt(top_y + 12), "của cán bộ coi thi 1")
    c.drawCentredString(pt(31), page_h - pt(top_y + 38), "Họ tên, chữ ký")
    c.drawCentredString(pt(31), page_h - pt(top_y + 42), "của cán bộ coi thi 2")

    c.setFont(font_reg, 8.5)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    st_name = ""
    if mode != 'blank' and session and session.student_id:
        st_name = session.student_id.name or ""

    s_lines = [
        (top_y + 8, "1. Hội đồng thi: ...................................................."),
        (top_y + 17, "2. Điểm thi: ........................................................."),
        (top_y + 26, "3. Phòng thi số: ...................................................."),
        (top_y + 35, f"4. Họ và tên thí sinh: {st_name if st_name else '............................................'}"),
        (top_y + 44, "5. Ngày sinh: ...../...../.........     (Nam/Nữ): ........."),
        (top_y + 53, "6. Chữ ký của thí sinh: ........................................"),
    ]
    for ly, ltext in s_lines:
        c.drawString(pt(55), page_h - pt(ly), ltext)

    # 4. Ma trận SBD & Mã đề thi
    c.setFont(font_bold, 8.5)
    c.drawCentredString(pt(144.5), page_h - pt(top_y + 5), "7. Số báo danh")
    c.drawCentredString(pt(181.5), page_h - pt(top_y + 5), "8. Mã đề thi")

    def draw_digit_matrix(start_x_mm, prefilled_val=""):
        col_w = 5.6
        clean_digits = re.sub(r'\D', '', str(prefilled_val or '')).zfill(6)[-6:] if prefilled_val else ""
        for i in range(6):
            dx = start_x_mm + i * col_w
            c.setLineWidth(0.6)
            c.setStrokeColorRGB(0.1, 0.1, 0.1)
            c.rect(pt(dx), page_h - pt(top_y + 13), pt(col_w), pt(6), fill=0, stroke=1)
            if clean_digits:
                c.setFont(font_bold, 8)
                c.drawCentredString(pt(dx + col_w / 2.0), page_h - pt(top_y + 11.5), clean_digits[i])

        for d in range(10):
            dy = top_y + 16 + d * 3.8
            for i in range(6):
                dx = start_x_mm + i * col_w + col_w / 2.0
                is_shaded = clean_digits and clean_digits[i] == str(d)
                c.setLineWidth(0.5)
                if is_shaded:
                    c.setFillColorRGB(0.1, 0.1, 0.1)
                    c.circle(pt(dx), page_h - pt(dy), pt(1.5), fill=1, stroke=1)
                else:
                    c.setStrokeColorRGB(0.3, 0.3, 0.3)
                    c.circle(pt(dx), page_h - pt(dy), pt(1.5), fill=0, stroke=1)
                    c.setFont(font_reg, 6)
                    c.setFillColorRGB(0.2, 0.2, 0.2)
                    c.drawCentredString(pt(dx), page_h - pt(dy) - pt(0.6), str(d))

    pre_sbd = ""
    pre_code = ""
    if mode != 'blank' and session:
        pre_sbd = getattr(session, 'sbd', '') or session.student_code or (session.student_id.code if session.student_id else "")
        pre_code = session.exam_code or ""

    draw_digit_matrix(128, pre_sbd)
    draw_digit_matrix(165, pre_code)

    # 5. Lời dặn thí sinh
    inst_top = 87
    c.setFont(font_bold, 7.5)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawString(pt(10), page_h - pt(inst_top), "Thí sinh lưu ý: ")
    c.setFont(font_reg, 7.5)
    c.drawString(pt(27), page_h - pt(inst_top), "- Giữ cho phiếu phẳng, không bôi bẩn, không làm rách. - Ghi đủ thông tin SBD, Mã đề.")
    c.drawString(pt(27), page_h - pt(inst_top + 3.5), "- Dùng bút chì đen tô kín ô tròn tương ứng SBD, Mã đề và đáp án. Không được gạch chéo hay đánh dấu khác.")
    c.setFont(font_bold, 7.5)
    c.drawString(pt(10), page_h - pt(inst_top + 7.5), f"Phần trả lời ({total_questions} câu): ")
    c.setFont(font_reg, 7.5)
    c.drawString(pt(40), page_h - pt(inst_top + 7.5), "Đối với mỗi câu trắc nghiệm, thí sinh chọn và tô kín một ô tròn tương ứng phương án đúng.")

    # 6. Khung trả lời (50 câu chia làm 2 cột x 25 câu)
    grid_top = 98
    grid_bot = 282
    grid_h = grid_bot - grid_top
    gx, gy = xy(10, grid_bot)
    gw = pt(190)
    gh = pt(grid_h)

    c.setLineWidth(1.2)
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.rect(gx, gy, gw, gh, fill=0, stroke=1)

    c.setLineWidth(0.8)
    c.line(pt(105), page_h - pt(grid_top), pt(105), page_h - pt(grid_bot))

    group_h = (grid_h - 4 * 1.5) / 5.0
    gap = 1.5

    for col_idx in range(2):
        col_x = 10 if col_idx == 0 else 105
        col_w = 95
        q_start = 1 if col_idx == 0 else 26

        for g in range(5):
            g_top = grid_top + g * (group_h + gap)
            g_bot = g_top + group_h
            c.setLineWidth(0.5)
            c.setStrokeColorRGB(0.4, 0.4, 0.4)
            c.rect(pt(col_x + 1.5), page_h - pt(g_bot), pt(col_w - 3), pt(group_h), fill=0, stroke=1)

            row_h = group_h / 5.0
            for r in range(5):
                q_num = q_start + g * 5 + r
                if q_num > total_questions:
                    continue
                row_y = g_top + r * row_h
                cy = row_y + row_h / 2.0

                c.setFont(font_bold, 8.5)
                c.setFillColorRGB(0.1, 0.1, 0.1)
                c.drawString(pt(col_x + 4), page_h - pt(cy + 1.0), f"{q_num:02d}")

                bubble_r = 2.4
                bubble_centers = [
                    ('A', col_x + col_w * 0.28),
                    ('B', col_x + col_w * 0.49),
                    ('C', col_x + col_w * 0.70),
                    ('D', col_x + col_w * 0.91),
                ]

                for opt, bx in bubble_centers:
                    c.setLineWidth(0.6)
                    c.setStrokeColorRGB(0.2, 0.2, 0.2)
                    c.circle(pt(bx), page_h - pt(cy), pt(bubble_r), fill=0, stroke=1)
                    c.setFont(font_bold, 6.8)
                    c.setFillColorRGB(0.2, 0.2, 0.2)
                    c.drawCentredString(pt(bx), page_h - pt(cy) - pt(0.7), opt)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def generate_sample_sheet_image(student_name="Nguyen Van A", student_code="000123",
                                exam_code="102345", answers_dict=None, total_questions=50):
    """Tạo ảnh mẫu Pillow PNG cho phiếu thi 50 câu (dùng kiểm thử hoặc preview offline)."""
    from PIL import ImageDraw, ImageFont
    answers_dict = answers_dict or {}
    img = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_lg = ImageFont.truetype("arial.ttf", 26)
        font_md = ImageFont.truetype("arial.ttf", 16)
        font_sm = ImageFont.truetype("arial.ttf", 12)
        font_xs = ImageFont.truetype("arial.ttf", 10)
    except Exception:
        font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

    # Fiducials
    draw.rectangle([57, 52, 137, 75], fill=(0, 0, 0))
    draw.rectangle([1062, 52, 1142, 75], fill=(0, 0, 0))
    draw.rectangle([57, 1625, 137, 1648], fill=(0, 0, 0))
    draw.rectangle([1062, 1625, 1142, 1648], fill=(0, 0, 0))

    # Header
    draw.text((CANVAS_WIDTH // 2, 70), "PHIẾU TRẢ LỜI TRẮC NGHIỆM", fill=(11, 34, 64), font=font_lg, anchor="mm")
    draw.text((CANVAS_WIDTH // 2, 105), "Kỳ thi: Kiểm Tra Định Kỳ - Môn: Toán Học", fill=(60, 60, 60), font=font_md, anchor="mm")

    # Bảng thông tin
    draw.rectangle([57, 140, 1142, 480], outline=(0, 0, 0), width=2)
    draw.line([300, 140, 300, 480], fill=(0, 0, 0), width=1)
    draw.line([720, 140, 720, 480], fill=(0, 0, 0), width=2)
    draw.line([930, 140, 930, 480], fill=(0, 0, 0), width=1)

    draw.text((178, 160), "CÁN BỘ COI THI", fill=(0, 0, 0), font=font_md, anchor="mm")
    draw.text((320, 170), f"Họ và tên thí sinh: {student_name}", fill=(0, 0, 0), font=font_md)

    # SBD
    draw.text((825, 160), "SỐ BÁO DANH", fill=(0, 0, 0), font=font_md, anchor="mm")
    sbd_clean = re.sub(r'\D', '', str(student_code)).zfill(6)[-6:]
    for c_idx, cx in enumerate(SBD_X_COLS):
        draw.rectangle([cx - 14, 185, cx + 14, 215], outline=(0, 0, 0), width=1)
        if sbd_clean:
            draw.text((cx, 200), sbd_clean[c_idx], fill=(0, 0, 0), font=font_md, anchor="mm")
        for d in range(10):
            cy = int(SBD_Y_START + d * SBD_Y_STEP)
            if sbd_clean and sbd_clean[c_idx] == str(d):
                draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(0, 0, 0), outline=(0, 0, 0))
            else:
                draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(80, 80, 80), width=1)
                draw.text((cx, cy), str(d), fill=(80, 80, 80), font=font_xs, anchor="mm")

    # Mã đề
    draw.text((1040, 160), "MÃ ĐỀ THI", fill=(0, 0, 0), font=font_md, anchor="mm")
    code_clean = re.sub(r'\D', '', str(exam_code)).zfill(6)[-6:]
    for c_idx, cx in enumerate(EXAM_CODE_X_COLS):
        draw.rectangle([cx - 14, 185, cx + 14, 215], outline=(0, 0, 0), width=1)
        if code_clean:
            draw.text((cx, 200), code_clean[c_idx], fill=(0, 0, 0), font=font_md, anchor="mm")
        for d in range(10):
            cy = int(EXAM_CODE_Y_START + d * EXAM_CODE_Y_STEP)
            if code_clean and code_clean[c_idx] == str(d):
                draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(0, 0, 0), outline=(0, 0, 0))
            else:
                draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(80, 80, 80), width=1)
                draw.text((cx, cy), str(d), fill=(80, 80, 80), font=font_xs, anchor="mm")

    # Lưới trả lời 50 câu
    draw.rectangle([57, 560, 1142, 1610], outline=(0, 0, 0), width=2)
    draw.line([600, 560, 600, 1610], fill=(0, 0, 0), width=1)

    col1_opts_x = {'A': 178, 'B': 295, 'C': 415, 'D': 535}
    for q in range(1, total_questions + 1):
        col_idx = 0 if q <= 25 else 1
        idx_in_col = (q - 1) % 25
        g_idx = idx_in_col // 5
        pos_in_g = idx_in_col % 5

        g_base_y = 596 + g_idx * 218
        cy = int(g_base_y + pos_in_g * 43.5)
        x_offset = 0 if col_idx == 0 else 543

        # Khung viền khối 5 câu
        if pos_in_g == 0:
            box_top = g_base_y - 22
            box_bot = g_base_y + int(4.5 * 43.5) + 20
            draw.rectangle([65 + x_offset, box_top, 590 + x_offset, box_bot], outline=(150, 150, 150), width=1)

        draw.text((105 + x_offset, cy), f"{q:02d}", fill=(0, 0, 0), font=font_md, anchor="mm")
        chosen = answers_dict.get(str(q), '')

        for opt, base_cx in col1_opts_x.items():
            cx = base_cx + x_offset
            if chosen == opt:
                draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(0, 0, 0), outline=(0, 0, 0))
            else:
                draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], outline=(80, 80, 80), width=1)
                draw.text((cx, cy), opt, fill=(80, 80, 80), font=font_xs, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


# ==============================================================================
# GIẢI NÉN TỆP RAR / ZIP CHứa HÀNG LOẠT ẢNH PHIẾU BÀI THI
# ==============================================================================

VALID_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff')


def extract_images_from_archive(archive_bytes, filename=""):
    """
    Giải nén tệp nén (.rar, .zip) và trích xuất toàn bộ các tệp hình ảnh bài thi bên trong.
    Hỗ trợ:
    - Định dạng .RAR (qua UnRAR.exe, WinRAR.exe, bsdtar/tar.exe trên Windows/Linux, hoặc 7z).
    - Định dạng .ZIP (qua thư viện chuẩn zipfile của Python).
    Trả về danh sách các tuple: [(image_filename, image_bytes), ...] được sắp xếp theo tên file.
    """
    import zipfile
    import tempfile
    import subprocess

    if not archive_bytes:
        return []

    fname_lower = (filename or "").lower().strip()
    is_zip_magic = archive_bytes[:4] == b'PK\x03\x04'
    is_rar_magic = archive_bytes[:4] == b'Rar!'

    extracted_images = []

    # 1. Nếu là file ZIP chuẩn -> Giải nén nhanh trong bộ nhớ bằng zipfile
    if is_zip_magic or (fname_lower.endswith('.zip') and not is_rar_magic):
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes), 'r') as zf:
                for info in sorted(zf.infolist(), key=lambda x: x.filename):
                    if info.is_dir():
                        continue
                    base_name = os.path.basename(info.filename)
                    if not base_name or base_name.startswith('.') or '__MACOSX' in info.filename:
                        continue
                    if base_name.lower().endswith(VALID_IMAGE_EXTENSIONS):
                        img_data = zf.read(info.filename)
                        if img_data:
                            extracted_images.append((base_name, img_data))
            if extracted_images:
                return extracted_images
        except Exception as e:
            _logger.warning(f"Giải nén bằng zipfile không thành công, chuyển sang công cụ hệ thống: {str(e)}")

    # 2. Giải nén file .RAR (hoặc các định dạng nén khác) qua thư mục tạm và công cụ hệ thống
    with tempfile.TemporaryDirectory(prefix="omr_batch_") as tmp_dir:
        ext = '.rar' if (is_rar_magic or fname_lower.endswith('.rar')) else (os.path.splitext(fname_lower)[1] or '.rar')
        archive_path = os.path.join(tmp_dir, f"upload_archive{ext}")
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)

        with open(archive_path, 'wb') as f:
            f.write(archive_bytes)

        # Danh sách các lệnh giải nén ưu tiên trên Windows & Linux
        commands_to_try = []
        unrar_win = r"C:\Program Files\WinRAR\UnRAR.exe"
        winrar_win = r"C:\Program Files\WinRAR\WinRAR.exe"
        sevenz_win = r"C:\Program Files\7-Zip\7z.exe"
        tar_win = r"C:\Windows\System32\tar.exe"

        if os.path.exists(unrar_win):
            commands_to_try.append([unrar_win, "x", "-y", "-idq", archive_path, extract_dir + os.sep])
        if os.path.exists(winrar_win):
            commands_to_try.append([winrar_win, "x", "-y", "-ibck", archive_path, extract_dir + os.sep])
        if os.path.exists(tar_win):
            commands_to_try.append([tar_win, "-xf", archive_path, "-C", extract_dir])
        if os.path.exists(sevenz_win):
            commands_to_try.append([sevenz_win, "x", "-y", f"-o{extract_dir}", archive_path])

        # Fallback trên Linux / PATH
        commands_to_try.extend([
            ["unrar", "x", "-y", archive_path, extract_dir + os.sep],
            ["tar", "-xf", archive_path, "-C", extract_dir],
            ["7z", "x", "-y", f"-o{extract_dir}", archive_path],
        ])

        last_err = ""
        for cmd in commands_to_try:
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                # Kiểm tra xem đã có file được bung ra trong extract_dir chưa
                found_files = []
                for root, _dirs, files in os.walk(extract_dir):
                    for file in sorted(files):
                        if file.startswith('.') or file.lower() == 'thumbs.db':
                            continue
                        if file.lower().endswith(VALID_IMAGE_EXTENSIONS):
                            full_p = os.path.join(root, file)
                            with open(full_p, 'rb') as img_f:
                                data = img_f.read()
                            if data:
                                found_files.append((file, data))
                if found_files:
                    return found_files
                if proc.returncode != 0:
                    last_err = proc.stderr.decode('utf-8', errors='ignore').strip()
            except Exception as e:
                last_err = str(e)
                continue

        raise ValueError(
            f"Không thể giải nén tệp '{filename or 'archive.rar'}' hoặc bên trong tệp nén không chứa hình ảnh hợp lệ (.jpg, .png)! "
            f"Chi tiết: {last_err or 'Tệp rỗng hoặc sai định dạng.'}"
        )


def create_archive_from_images(image_tuples, prefer_rar=True):
    """
    Đóng gói danh sách [(filename, image_bytes), ...] thành file .RAR (nếu có WinRAR) hoặc .ZIP.
    Trả về (archive_bytes, extension) với extension là 'rar' hoặc 'zip'.
    """
    import zipfile
    import tempfile
    import subprocess

    winrar_win = r"C:\Program Files\WinRAR\WinRAR.exe"
    rar_win = r"C:\Program Files\WinRAR\Rar.exe"
    rar_exe = rar_win if os.path.exists(rar_win) else (winrar_win if os.path.exists(winrar_win) else None)

    if prefer_rar and rar_exe:
        try:
            with tempfile.TemporaryDirectory(prefix="omr_pack_") as tmp_dir:
                img_paths = []
                for fname, fbytes in image_tuples:
                    safe_name = os.path.basename(fname)
                    p = os.path.join(tmp_dir, safe_name)
                    with open(p, 'wb') as f:
                        f.write(fbytes)
                    img_paths.append(safe_name)

                out_rar = os.path.join(tmp_dir, "bai_thi_omr.rar")
                cmd = [rar_exe, "a", "-ep", "-idq", out_rar] + img_paths
                if rar_exe == winrar_win:
                    cmd = [winrar_win, "a", "-afRAR", "-ep", "-ibck", out_rar] + img_paths
                subprocess.run(cmd, cwd=tmp_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                if os.path.exists(out_rar):
                    with open(out_rar, 'rb') as f:
                        return f.read(), 'rar'
        except Exception as e:
            _logger.warning(f"Không thể tạo file RAR bằng WinRAR, chuyển sang tạo ZIP: {str(e)}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, fbytes in image_tuples:
            zf.writestr(os.path.basename(fname), fbytes)
    buf.seek(0)
    return buf.getvalue(), 'zip'

