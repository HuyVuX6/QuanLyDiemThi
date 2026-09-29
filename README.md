# QuanLyDiemThi - Educational System (Toán Lớp 3 & Phân Tích Claude AI)

Hệ thống quản lý học tập, đề thi, lượt làm bài môn Toán lớp 3 và tích hợp phân tích sư phạm tự động qua Claude AI trên nền tảng Odoo 19.

## 🌟 Tính Năng Chính
- 📊 **Bảng Điều Khiển (Dashboard):** Tổng quan KPI sĩ số học sinh, số đề thi, lượt làm bài, tỷ lệ đạt/giỏi, tích hợp các phím tắt nhanh.
- 📈 **Báo Cáo & Thống Kê Đa Chiều:**
  - Biểu đồ thống kê điểm số theo lớp & đề thi (Graph View).
  - Ma trận phân tích kết quả học tập (Pivot View).
  - Phân tích ngân hàng câu hỏi theo dạng toán (Cộng, Trừ, Nhân, Chia, Hình học, Toán có lời văn) và độ khó.
- 🏫 **Quản Lý Trường Lớp & Học Sinh:** Khối lớp, Lớp học, Học sinh, Giáo viên chủ nhiệm.
- 📝 **Ngân Hàng Câu Hỏi & Đề Thi:** Tạo đề kiểm tra 15 phút, giữa kỳ, cuối kỳ với tính năng chấm điểm tự động.
- 🤖 **Phân Tích Sư Phạm Claude AI:** Đánh giá điểm mạnh, điểm yếu, phản hồi sư phạm và gợi ý lộ trình ôn tập cho từng học sinh.

## 🛠️ Cài Đặt & Sử Dụng
- Đặt thư mục `custom_addons` vào `addons_path` trong cấu hình Odoo (`odoo.conf`).
- Nâng cấp module: `odoo-bin -u educational_system -d <database_name>`
- Khởi động lại dịch vụ Odoo.
