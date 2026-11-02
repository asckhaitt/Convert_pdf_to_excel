"""Hướng dẫn sử dụng bằng ngôn từ kế toán."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

HELP = """
<h2>Hướng dẫn sử dụng</h2>
<p><b>Bước 1 – Chọn dữ liệu.</b> Bấm “Chọn tệp PDF…” để chọn một hoặc nhiều sổ nhật ký chung
dạng PDF scan, hoặc “Chọn thư mục chứa PDF…” để chọn cả thư mục. File chọn nhầm có thể bỏ
khỏi danh sách bằng nút “Bỏ file đã chọn”.</p>
<p><b>Bước 2 – Chọn nơi lưu Excel.</b> Phần mềm đề xuất thư mục con
<i>Excel_da_chuyen_doi</i> cạnh dữ liệu đầu vào; có thể đổi sang thư mục khác.</p>
<p><b>Bước 3 – Bắt đầu chuyển đổi.</b> Mỗi trang được đọc, nhận diện bảng, đọc dữ liệu rồi
đối soát; cuối cùng file Excel được tạo và mở lại để kiểm tra. Thanh tiến trình tổng chỉ
đạt 100% khi Excel đã lưu và kiểm tra xong. Có thể bấm “Dừng xử lý”; các trang đã xong được
giữ lại và lần sau chạy tiếp từ chỗ đã dừng.</p>
<h3>Hai trạng thái cần phân biệt</h3>
<p><b>Trạng thái đối chiếu:</b> “Cần đối chiếu” là file nháp, chưa ai xác nhận khớp ảnh PDF.
“Đã đối chiếu khớp PDF” chỉ đạt khi đã xử lý đủ 100% số trang, từng trang được xác nhận,
mọi dòng đã phân loại, không còn cảnh báo trích xuất chưa xử lý và các công thức chuyển
trang khớp (hoặc sai lệch đã được xác nhận là do chính PDF gốc).</p>
<p><b>Kiểm tra kế toán</b> là việc riêng: “Cân đối”, “Có sai lệch trên PDF gốc” hoặc
“Chưa kiểm tra xong”. Sổ gốc in không cân thì phần mềm giữ nguyên số, không tự sửa.</p>
<h3>Đối chiếu từng trang</h3>
<p>Bấm “Đối soát” ở bảng kết quả. Bên trái là ảnh trang PDF (phóng to, thu nhỏ, kéo ảnh,
ô đang chọn được tô sáng); bên phải là lưới 8 cột sửa trực tiếp. Dùng bộ lọc và nút
“Cảnh báo trước / Cảnh báo tiếp theo” để đi tới từng chỗ nghi ngờ. Sửa xong bấm
“Lưu đối soát”; phần mềm tự chạy lại các kiểm tra nhưng không tự đổi số liệu.</p>
<p>Nếu nghi chính PDF in sai, chọn cảnh báo rồi bấm “Xác nhận sai lệch trên PDF gốc”:
số liệu giữ đúng như bản in và cảnh báo kế toán vẫn được ghi ở sheet Đối soát.</p>
<p>Xác nhận từng dòng, từng trang sau khi đã nhìn ảnh. Khi đủ điều kiện, bấm
“Xuất Excel đã đối chiếu” để nhận file cuối; file nháp luôn có hậu tố _CHUA_XAC_NHAN,
file cuối có hậu tố _DA_DOI_CHIEU. Phần mềm không bao giờ ghi đè file đã có.</p>
<h3>Sheet trong file Excel</h3>
<p><b>Nhật ký chung:</b> đúng 8 cột, giữ thứ tự dòng như sổ, ô trống giữ trống, ngày dạng
dd/mm/yyyy, mã số giữ dạng chữ để không mất số 0 đầu, số tiền là số thật.</p>
<p><b>Đối soát:</b> số chuyển trang từng trang, chênh lệch, cảnh báo kế toán và lý do các
dòng bị loại (tiêu đề, dòng chuyển trang, tổng cộng…).</p>
<p><b>Thông tin:</b> tên PDF, số trang, ngày giờ xử lý, phiên bản phần mềm và trạng thái.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hướng dẫn sử dụng")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(HELP)
        browser.setOpenExternalLinks(False)
        lay.addWidget(browser)