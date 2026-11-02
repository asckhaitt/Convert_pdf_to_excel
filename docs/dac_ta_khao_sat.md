# Đặc tả khảo sát — Sổ Nhật Ký Chung S03a-DN (bản scan)

Phạm vi khảo sát: 5 tệp PDF trong thư mục `PDF file/` (Sổ Nhật Ký Chung các năm 2015–2019
của cùng một đơn vị). Toàn bộ là **ảnh quét, không có lớp chữ** (kiểm tra bằng số từ trích
được từ PDF = 0). Ảnh render 300 DPI, kích thước 3509×2481 px, bảng kẻ ô chấm/vạch mờ.

Số trang từng tệp: 2015: 36 · 2016: 30 · 2017: 34 · 2018: 34 · 2019: 34.

## 1. Cấu trúc bảng trên mỗi trang sổ

- 8 cột đúng mẫu S03a-DN: Ngày hạch toán, Ngày chứng từ, Số chứng từ, Diễn giải,
  Tài khoản, TK đối ứng, Phát sinh Nợ, Phát sinh Có. Chiều rộng cột không đều
  (cột Diễn giải rộng nhất, ~576 px ở 300 DPI; hai cột tài khoản ~170 px).
- Dòng tiêu đề cột lặp lại ở đầu mỗi trang (chữ in hoa, không có số tiền).
- Dòng “Số trang trước chuyển sang” ở đầu trang (trừ trang đầu sổ).
- Dòng “Cộng chuyển sang trang sau” ở cuối trang (trừ trang cuối sổ).
- Trang cuối sổ có dòng “Tổng cộng” thay cho dòng chuyển trang sau.
- **Ngoài khung bảng** (chân trang) nhiều trang in lại số chuyển trang/tổng cộng;
  phần mềm đọc thêm vùng chân trang để đối chiếu chéo (`_read_footer_totals`).
- Chân trang góc phải in số trang dạng `n/tổng` (ví dụ `34/36`).

## 2. Đặc tả các loại dòng (chốt sau khảo sát)

| Loại | Dấu hiệu nhận biết | Xử lý |
|---|---|---|
| HEADER | ô diễn giải chứa “Diễn giải”, không số tiền, không tài khoản số | loại khỏi sheet nghiệp vụ, ghi lý do ở Đối soát |
| CARRY_IN | diễn giải “Số trang trước chuyển sang” | chỉ giữ ở sheet Đối soát |
| CARRY_OUT | diễn giải “Cộng chuyển sang trang sau” | chỉ giữ ở sheet Đối soát |
| GRAND_TOTAL | nhãn “Tổng cộng” (OCR có thể đọc lệch: “1ong cong”, “T6ng c6ng”…) | chỉ giữ ở sheet Đối soát |
| ENTRY | có số tiền hoặc có ngày/số chứng từ/tài khoản | đưa vào sheet “Nhật ký chung” |
| UNKNOWN | không khớp loại nào | cảnh báo, người soát phân loại lại |
| INFO (trang) | trang không có bảng (trang ký tên/đóng dấu, ghi chú) | không vào sheet nghiệp vụ, cảnh báo INFO |

Dòng diễn giải nối dài (chỉ có chữ ở cột Diễn giải, các cột khác trống) được ghép vào ô
diễn giải của dòng bút toán liền trước (một ô nhiều dòng), có cảnh báo INFO để người soát xác nhận.

## 3. Các phát hiện đặc biệt của dữ liệu thật

1. **Trang ký tên**: tệp 2015, trang PDF thứ 35 là trang “Sổ này có 36 trang…” có chữ ký,
   không có bảng → loại INFO, không tính vào chuỗi chuyển trang.
2. **Thứ tự trang in lệch thứ tự PDF**: cùng tệp 2015, trang PDF 35 in số trang `36/36`
   (trang ký) còn trang PDF 36 in `35/36` (trang nghiệp vụ cuối). Phần mềm giữ nguyên thứ tự
   PDF và nêu cảnh báo `SO_TRANG_IN_LECH` để người soát đối chiếu; không tự sắp xếp lại.
3. **Nhãn “Tổng cộng” in tràn** sang các cột trái của ô Diễn giải ở trang cuối: ô Diễn giải
   trống nên phần mềm đọc nhãn từ vùng cột trái (`left_label`) để phân loại.
4. **Chân trang in đậm bị nhòe**: số Có tổng của trang 34 (tệp 2015) in `…368.000.000` nhưng
   vết mực làm OCR đọc `…366.000.000`. Đây là lỗi ảnh quét thật; phần mềm **không tự sửa**,
   công thức chuỗi trang nêu chênh lệch để người soát xác nhận “sai lệch trên PDF gốc”.
5. **Số trang in ở chân trang rất khó đọc** (chữ nhỏ, mờ): thử mọi cấu hình Tesseract
   (vie, eng, vie+eng, psm 6/7/8/13, phóng 2–4 lần) vẫn sai (ví dụ `2/36` đọc thành `2/30`,
   `2/46`). Chốt: đọc best-effort phần tử số; nếu không đọc được nêu cảnh báo INFO và
   người soát nhập số trang in bằng ô số trên màn hình đối soát.
6. **Chữ số chạm kẻ bảng**: chữ số cuối cột tiền sát kẻ phải → nới biên phải +6 px khi cắt ô;
   chữ số đầu cột tài khoản sát kẻ trái → nới biên trái riêng cho hai cột tài khoản.
7. **Số chứng từ OCR không thống nhất** (I/1, O/0, S/5, B/8…): nhóm chứng từ dùng khóa
   chịu nhầm lẫn ký tự; các dạng khác nhau vẫn được liệt kê bằng cảnh báo INFO để người soát
   chọn dạng đúng; chỉ tự gộp hai nhóm liền nhau khi hơn kém 1 ký tự **và** gộp lại cân Nợ=Có.

## 4. Cấu hình OCR đã chốt (Tesseract 5.5.1, tessdata_best)

| Loại ô | Ngôn ngữ | Whitelist | PSM |
|---|---|---|---|
| ngày | vie | `0123456789/` | 7 |
| số tiền | vie | `0123456789.,()-` | 7 |
| số chứng từ | vie | chữ+`0123456789./-` | 8 |
| tài khoản | **eng** | `0123456789` | 7 |
| diễn giải/nhãn | vie | không | 7 |

Lý do dùng eng cho cột tài khoản: bộ `vie` đọc chữ số in chân gạch (serif) thành chữ cái
(ví dụ `1111` → `HXIII`); bộ eng với whitelist chữ số đọc đúng.

**Lệch so với kế hoạch gốc**: kế hoạch nêu PaddleOCR, nhưng gói PaddleOCR offline không kèm
từ điển tiếng Việt và mô hình nặng; đã chuyển sang Tesseract + tessdata_best `vie`/`eng`
nhúng trong bản đóng gói. Chức năng và yêu cầu offline không đổi.

## 5. Quy tắc số liệu (giữ nguyên theo kế hoạch)

- Số tiền nội bộ dùng `Decimal`; Excel ghi kiểu số, ngày kiểu ngày `dd/mm/yyyy`,
  mã (số chứng từ, tài khoản) ghi kiểu text để giữ số 0 đứng đầu; ô trống giữ trống.
- Không suy đoán điền ô trống, không tự cân đối số liệu; sai lệch nguồn chỉ được ghi nhận
  ở sheet “Đối soát” sau khi người soát xác nhận.
