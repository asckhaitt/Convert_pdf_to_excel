Dựa trên [PDF mẫu](file:///D:/Project/Convert_pdf_to_excel/PDF%20file/SO%20NKC%202015%20CTY%20NGOC%20HA.pdf) và [mockup](file:///D:/Project/Convert_pdf_to_excel/Man_hinh_mockup_du_kien.png), em đề xuất kế hoạch triển khai như sau.

> **Điểm phải nói rõ:** không có OCR nào bảo đảm tự động đúng 100%, đặc biệt với dấu tiếng Việt và số tiền. Cân Nợ/Có cũng không chứng minh dữ liệu đúng tuyệt đối vì hai lỗi có thể triệt tiêu nhau.  
> Mục tiêu khả thi là: **tự động trích xuất, đối soát toàn diện và chỉ xuất Excel “Đã đối chiếu khớp PDF” sau khi kế toán viên đã xác nhận đủ phạm vi dữ liệu.**

---

# 1. Mục tiêu nghiệm thu

Phần mềm phải đáp ứng:

1. Chuyển đúng mẫu **Sổ Nhật ký chung S03a-DN** thành Excel.
2. “Khớp 100%” được hiểu là **khớp giá trị dữ liệu và thứ tự dòng hạch toán trên PDF sau khi loại các dòng không phải bút toán**, không phải tái dựng nguyên xi bố cục in ấn. Không tự điền hoặc suy ra giá trị cho ô đang trống trên PDF.
3. Giữ đúng thứ tự các dòng hạch toán, không thiếu hoặc nhân đôi dòng.
4. Loại khỏi sheet nghiệp vụ:
   - Thông tin doanh nghiệp, mẫu số, tiêu đề lặp lại.
   - Tiêu đề cột lặp lại trên từng trang.
   - Số trang.
   - **Số trang trước chuyển sang**.
   - **Cộng chuyển sang trang sau**.
   - Các dòng không phải bút toán khác được xác định trong giai đoạn khảo sát.
5. Hai dòng chuyển trang tuy không xuất vào sheet nghiệp vụ nhưng **phải được đọc, lưu tại sheet “Đối soát” và dùng để kiểm tra**.
6. Chọn được:
   - Một thư mục chứa nhiều PDF.
   - Một hoặc nhiều file PDF cụ thể.
7. Hiển thị tiến trình, đồng hồ chạy thực tế, file/trang đang xử lý.
8. Kế toán viên ít kinh nghiệm CNTT vẫn sử dụng được: chọn file, bắt đầu, xử lý cảnh báo, mở Excel.
9. Xử lý hoàn toàn **offline trên máy Windows**, không gửi dữ liệu kế toán lên cloud.
10. Bàn giao **duy nhất một file `ChuyenSoNhatKyChung.exe`**, không cần cài đặt, không cần Python và không cần tải thêm mô hình hoặc thư viện.

---

# 2. Trạng thái đối chiếu và kiểm tra kế toán

## 2.1. Hai trạng thái đối chiếu bắt buộc

### Trạng thái 1: “Cần đối chiếu”

Đây là kết quả sau khi trích xuất tự động:

- Đã trích xuất dữ liệu.
- Có thể xuất Excel nháp.
- Còn ô nghi ngờ hoặc cảnh báo trích xuất chưa xử lý.
- Tên file có hậu tố `_CHUA_XAC_NHAN.xlsx`.

### Trạng thái 2: “Đã đối chiếu khớp PDF”

Chỉ đạt khi thỏa toàn bộ điều kiện:

- 100% trang đã xử lý, không có trang bị bỏ qua.
- Kế toán viên đã xác nhận từng trang trong chế độ nghiêm ngặt.
- 100% dòng nguồn đã được phân loại, không còn dòng chưa rõ.
- Không còn ô nghi ngờ chưa xem hoặc cảnh báo trích xuất chưa xử lý.
- Dữ liệu đã duyệt khớp giá trị trên PDF; mọi sửa đổi chỉ nhằm khắc phục lỗi trích xuất và phải được đối chiếu với ảnh nguồn.
- Các công thức chuyển trang áp dụng được phải có chênh lệch bằng `0`; nếu chính PDF in sai, sai lệch phải được kế toán viên xác nhận là **sai lệch nguồn** và ghi rõ tại sheet “Đối soát”.
- File Excel sau xuất được mở lại và kiểm tra khớp 100% giá trị với dữ liệu đã duyệt.
- Tên file cuối có hậu tố `_DA_DOI_CHIEU.xlsx`.

**Nếu còn cảnh báo trích xuất chưa xử lý hoặc trang chưa được xác nhận, phần mềm không cho phép xuất file cuối với trạng thái “Đã đối chiếu khớp PDF”.**

## 2.2. Kiểm tra kế toán là trạng thái độc lập

Kết quả kiểm tra kế toán gồm:

- **Cân đối**.
- **Có sai lệch trên PDF gốc**.
- **Chưa kiểm tra xong**.

Chứng từ không cân, tổng Nợ/Có không cân hoặc dòng chuyển trang in sai trên PDF **không được tự sửa**. Sau khi kế toán viên xác nhận đó là sai lệch của nguồn, file vẫn có thể đạt trạng thái **“Đã đối chiếu khớp PDF”**, nhưng sheet “Đối soát” phải tiếp tục thể hiện cảnh báo kế toán và số tiền chênh lệch.

Nếu trang quá mờ, thiếu trang hoặc kế toán viên không thể xác nhận giá trị trên ảnh nguồn thì file vẫn ở trạng thái **“Cần đối chiếu”**.

---

# 3. Công nghệ đề xuất

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Giao diện Windows | **PySide6** | Màn hình chính, đối soát ảnh và dữ liệu |
| Đọc PDF | **PyMuPDF** | Đếm trang, đọc text layer, chuyển trang PDF thành ảnh |
| Xử lý ảnh | **OpenCV** | Chỉnh nghiêng, nhận diện khung bảng, tách ô |
| OCR | **PaddleOCR tiếng Việt** | Đọc diễn giải, chứng từ, tài khoản, số tiền trên trang scan |
| Xuất Excel | **openpyxl** | Tạo và kiểm tra lại file `.xlsx` |
| Lưu phiên xử lý | **SQLite** | Lưu dữ liệu, tiến trình, lịch sử sửa |
| Chạy nền | **QThread** | Không làm treo giao diện khi xử lý |
| Cập nhật thời gian | **QTimer** | Cập nhật đồng hồ mỗi giây, độc lập với tiến trình xử lý |
| Kiểm thử | **pytest, pytest-qt** | Kiểm tra nghiệp vụ và giao diện |
| Đóng gói | **PyInstaller one-file** | Tạo duy nhất một `.exe` portable, không cần cài đặt |

**Không sử dụng Inno Setup hoặc bộ cài đặt.** Toàn bộ Python runtime, thư viện, tài nguyên và mô hình OCR phải được nhúng trong file `.exe`; chương trình không được yêu cầu tải mô hình khi mở lần đầu. Phải đóng gói thử và chạy trên Windows sạch ngay trong giai đoạn PoC để phát hiện sớm lỗi thư viện native và tài nguyên đi kèm.

Với bảng 8 cột có khung kẻ và bố cục cố định, em đề xuất **OpenCV làm phương pháp tách bảng chính**. `img2table` chỉ nên thử so sánh trong giai đoạn PoC, vì phần mềm cần kiểm soát chính xác từng ô, dòng gộp và tọa độ nguồn.

---

# 4. Cấu trúc file Excel

Đề xuất **mỗi PDF tạo một file Excel**, gồm 3 sheet.

## Sheet “Nhật ký chung”

Chỉ chứa dữ liệu hạch toán với đúng 8 cột:

1. Ngày hạch toán.
2. Ngày chứng từ.
3. Số chứng từ.
4. Diễn giải.
5. Tài khoản.
6. TK đối ứng.
7. Phát sinh Nợ.
8. Phát sinh Có.

Quy tắc:

- Một dòng Excel tương ứng một dòng hạch toán trên PDF.
- Giữ nguyên thứ tự nguồn.
- Không chứa dòng chuyển trang hoặc thông tin lặp lại.
- Với chứng từ nhiều dòng, **ô ngày và số chứng từ nào để trống trên PDF thì vẫn để trống trong Excel**. Không tự lặp hoặc điền giá trị suy ra; việc liên kết các dòng cùng chứng từ được thực hiện trong dữ liệu nội bộ để đối soát.
- Diễn giải nhiều dòng được giữ trong cùng một ô.
- Không thêm cột kỹ thuật vào sheet này.

## Sheet “Đối soát”

Bao gồm:

- Tổng Nợ/Có từng trang.
- Số trang trước chuyển sang.
- Tổng phát sinh trong trang.
- Cộng chuyển sang trang sau.
- Chênh lệch từng công thức.
- Sai lệch được xác nhận là do PDF gốc, nếu có.
- Tổng Nợ/Có toàn sổ.
- Số dòng hạch toán.
- Danh sách dòng không đưa vào sheet nghiệp vụ và lý do loại.
- Trạng thái đối chiếu PDF và kết quả kiểm tra kế toán, trình bày thành hai nội dung riêng.

Các dòng chuyển trang và dòng thông tin bị loại chỉ xuất hiện tại sheet này để phục vụ kiểm soát, **không xuất hiện như dòng hạch toán tại sheet “Nhật ký chung”**.

## Sheet “Thông tin”

Bao gồm:

- Tên PDF nguồn.
- Mã SHA-256 của PDF.
- Số trang.
- Ngày giờ xử lý.
- Phiên bản phần mềm và mô hình OCR.
- Trạng thái **“Cần đối chiếu”** hoặc **“Đã đối chiếu khớp PDF”**.
- Kết quả kiểm tra kế toán độc lập.

## Kiểu dữ liệu Excel

- Ngày: kiểu ngày Excel, hiển thị `dd/mm/yyyy`.
- Số chứng từ và tài khoản: kiểu văn bản, không làm mất số `0` đầu.
- Phát sinh Nợ/Có: kiểu số, giữ đúng số chữ số thập phân trên PDF. Chỉ dùng số nguyên VND sau khi giai đoạn khảo sát xác nhận toàn bộ dữ liệu không có phần thập phân.
- Nhận diện và giữ đúng số âm, số trong ngoặc, dấu chấm/dấu phẩy theo mẫu nguồn; không tự làm tròn.
- Ô tiền trống trên PDF vẫn để trống, không tự chuyển thành `0`.
- Không sử dụng macro hoặc liên kết ngoài.
- Có bộ lọc, cố định dòng tiêu đề, tự xuống dòng cho diễn giải.
- Không tự ghi đè file Excel đã tồn tại.

---

# 5. Quy trình xử lý chi tiết

## Bước 1 — Tiếp nhận PDF

- Cho phép chọn thư mục hoặc nhiều file.
- Loại trùng khi cùng một đường dẫn được chọn nhiều lần; nếu hai file khác đường dẫn có cùng mã SHA-256 thì phải thông báo và để kế toán viên quyết định, không tự bỏ file.
- Kiểm tra PDF hỏng, mã hóa hoặc không có quyền đọc.
- Kiểm tra thư mục đầu ra có ghi được không.
- Đếm số trang trước khi bắt đầu.
- Tính mã SHA-256 để phát hiện PDF bị thay đổi giữa chừng.
- Không thay đổi file PDF gốc.

## Bước 2 — Xem trước nhanh

- Chỉ xử lý tối đa 2 trang đầu khi bật “Xem trước nhanh”.
- Hiển thị ảnh PDF và dữ liệu trích xuất.
- Cho phép kiểm tra chất lượng trước khi chạy toàn bộ.
- Kết quả xem trước luôn ở trạng thái **“Cần đối chiếu”**.

## Bước 3 — Đọc text layer, tạo ảnh và tiền xử lý

- Kiểm tra text layer theo từng trang vì một PDF có thể gồm cả trang có văn bản và trang scan.
- Nếu text layer có đủ văn bản và tọa độ đáng tin cậy, ưu tiên trích xuất trực tiếp theo vùng ô để giảm lỗi OCR; nếu thiếu hoặc sai vị trí thì chuyển sang OCR cho trang đó.
- Dữ liệu lấy từ text layer vẫn phải đi qua đầy đủ các bước phân loại, đối soát và xác nhận như dữ liệu OCR.
- Chuyển PDF thành ảnh ở 300 DPI ban đầu cho trang cần OCR và để hiển thị đối chiếu.
- Giữ ảnh gốc để đối chiếu.
- Tạo ảnh xử lý riêng:
  - Xoay đúng hướng.
  - Chỉnh nghiêng nhẹ.
  - Tăng độ tương phản.
  - Giảm nhiễu có kiểm soát.
- Không làm nhị phân hóa quá mạnh vì có thể mất dấu tiếng Việt hoặc dấu chấm trong số tiền.

## Bước 4 — Nhận diện bảng

- Nhận diện đường kẻ ngang và dọc.
- Xác định vùng bảng và ranh giới 8 cột.
- Đối chiếu tiêu đề cột để tránh nhận sai vị trí.
- Xử lý đường kẻ đứt hoặc mờ.
- Nếu không xác định chắc chắn dòng/ô, phải tạo cảnh báo.
- Không được bỏ vùng ảnh chỉ vì không ghép được vào bảng.

## Bước 5 — Trích xuất theo từng loại ô

Không OCR toàn trang rồi đoán vị trí; cần trích xuất theo vùng:

- Trích xuất cấp ô cho ngày, số chứng từ, tài khoản và số tiền.
- Trích xuất cấp vùng cho diễn giải nhiều dòng.
- Với trang scan, OCR theo đúng vùng ô đã nhận diện; với trang có text layer đáng tin cậy, lấy văn bản theo tọa độ của cùng vùng ô.
- Lưu tọa độ từng ô để tô sáng trên ảnh khi đối soát.
- Lưu cả:
  - Văn bản trích xuất gốc từ OCR hoặc text layer.
  - Giá trị sau chuẩn hóa.
  - Độ tin cậy OCR, nếu có.
  - Cảnh báo liên quan.

## Bước 6 — Chuẩn hóa dữ liệu

Mỗi loại ô có quy tắc riêng:

### Ngày

- Kiểm tra ngày hợp lệ.
- Không tự hoán đổi ngày hạch toán và ngày chứng từ.
- Ngày mơ hồ phải đưa vào đối soát.

### Số chứng từ

- Giữ ở dạng văn bản.
- Không tự bỏ số `0` đầu.
- Không tự đoán hoặc điền số chứng từ bị thiếu.
- Không tự lặp ngày hoặc số chứng từ vào các dòng đang trống trên PDF.

### Diễn giải

- Giữ dấu tiếng Việt.
- Giữ xuống dòng khi cần.
- Không dùng công cụ chính tả để tự sửa nội dung kế toán.

### Tài khoản và TK đối ứng

- Kiểm tra ký tự không phù hợp.
- Các trường hợp `0/O`, `1/I`, `5/S`, `8/B` phải được đánh dấu nghi ngờ.
- Không suy ra tài khoản từ diễn giải.

### Số tiền

- Kiểm tra cấu trúc số, dấu chấm/dấu phẩy, dấu âm và số trong ngoặc theo mẫu nguồn.
- Giữ đúng phần thập phân nếu có; không tự làm tròn hoặc chuyển thành số nguyên khi chưa được phép.
- Dùng kiểu số thập phân chính xác `Decimal` cho tính toán và đối soát nội bộ, không dùng `float`.
- Ô trống phải giữ là trống, không chuyển thành `0`.
- Không tự sửa một chữ số để làm cho bút toán cân.
- Nếu kết quả mơ hồ, bắt buộc xem ảnh gốc.

## Bước 7 — Ghép dòng và chứng từ

- Ghép các dòng chữ thuộc cùng diễn giải.
- Ghép nhiều dòng Nợ/Có của cùng chứng từ.
- Hỗ trợ chứng từ kéo dài qua trang.
- Không nhóm chỉ bằng số chứng từ vì có thể trùng.
- Cho phép kế toán viên tách/gộp dòng nếu nhận diện sai ranh giới.

## Bước 8 — Phân loại dòng nguồn

Mỗi dòng phải thuộc một nhóm:

1. Dòng hạch toán.
2. Số trang trước chuyển sang.
3. Cộng chuyển sang trang sau.
4. Dòng tiêu đề/thông tin được phép loại.
5. Dòng chưa rõ — bắt buộc đối soát.

**Không xóa dòng ngay sau OCR.** Dòng bị loại vẫn phải được lưu cùng lý do để kiểm tra lại.

---

# 6. Quy tắc đối soát kế toán

Với mỗi trang `p`:

- `Vào_p`: số trên dòng “Số trang trước chuyển sang”.
- `PhátSinh_p`: tổng các dòng hạch toán thực tế trong trang, không gồm các dòng chuyển trang.
- `Ra_p`: số trên dòng “Cộng chuyển sang trang sau”.

## Đối soát trong từng trang

```text
Vào_p_Nợ + PhátSinh_p_Nợ = Ra_p_Nợ
Vào_p_Có + PhátSinh_p_Có = Ra_p_Có
```

Chỉ áp dụng công thức khi các thành phần bắt buộc tồn tại theo mẫu và đã được đọc chắc chắn:

- Trang đầu không có “Số trang trước chuyển sang” và trang cuối không có “Cộng chuyển sang trang sau” phải áp dụng quy tắc riêng đã chốt trong giai đoạn khảo sát.
- Ô trống không được mặc định là `0`.
- Trang ở giữa thiếu dòng chuyển trang, đọc không rõ hoặc sai cấu trúc phải tạo cảnh báo trích xuất, không được bỏ qua công thức một cách âm thầm.
- Không nối chuỗi chuyển trang giữa hai PDF khác nhau.

Nếu sai lệch, phần mềm hiển thị:

- Số in trên PDF.
- Tổng đang trích xuất.
- Số tiền chênh lệch.
- Các dòng liên quan để kế toán viên kiểm tra.

Nếu sau đối chiếu, toàn bộ số trích xuất đều khớp số in trên PDF nhưng công thức vẫn sai thì ghi nhận **“Sai lệch trên PDF gốc”**. Không sửa số liệu để làm công thức bằng `0`.

## Đối soát giữa hai trang

```text
Ra_p_Nợ = Vào_(p+1)_Nợ
Ra_p_Có = Vào_(p+1)_Có
```

Điều này giúp phát hiện:

- Thiếu dòng.
- Nhân đôi dòng.
- Sai số tiền.
- Sai chính dòng chuyển trang.
- Thiếu, trùng hoặc sai thứ tự trang.

Phần mềm phải theo dõi cả chỉ số trang trong PDF và số trang in trên tài liệu. Nếu hai thông tin không liên tục hoặc không khớp quy tắc của mẫu thì phải cảnh báo, không tự bỏ trang hoặc đổi thứ tự trang.

## Đối soát chứng từ

```text
Tổng Phát sinh Nợ của chứng từ
= Tổng Phát sinh Có của chứng từ
```

- Chỉ đối soát sau khi đã ghép đủ các dòng của chứng từ, kể cả chứng từ kéo dài qua trang.
- Nếu không cân: chỉ cảnh báo, không tự thêm bút toán, đổi tài khoản hoặc sửa số tiền để ép cân.

## Đối soát toàn sổ

```text
Tổng Nợ toàn sổ = Tổng Có toàn sổ
Chênh lệch = Tổng Nợ - Tổng Có = 0
```

Kết quả đối soát chứng từ và toàn sổ là **kiểm tra kế toán độc lập**, không đồng nghĩa với lỗi chuyển đổi:

- Nếu PDF gốc thật sự không cân, kế toán viên xác nhận sai lệch nguồn; phần mềm giữ nguyên số liệu và ghi rõ tại sheet “Đối soát”. File vẫn có thể đạt **“Đã đối chiếu khớp PDF”** khi đủ các điều kiện đối chiếu nguồn.
- Nếu chưa phân biệt được lỗi trích xuất hay sai lệch nguồn, file vẫn ở trạng thái **“Cần đối chiếu”**.
- Nếu PDF quá mờ hoặc thiếu dữ liệu khiến kế toán viên không thể xác nhận giá trị nguồn, không cấp trạng thái **“Đã đối chiếu khớp PDF”**.

---

# 7. Màn hình đối soát và sửa dữ liệu

Đây là phần bắt buộc để hướng tới độ khớp 100%.

## Bên trái: Ảnh PDF

- Hiển thị đúng trang nguồn.
- Phóng to, thu nhỏ, kéo ảnh.
- Tô sáng dòng hoặc ô đang chọn.
- Chuyển giữa ảnh gốc và ảnh đã xử lý.
- Có nút chuyển đến trang trước/sau.

## Bên phải: Dữ liệu trích xuất

- Lưới 8 cột.
- Cho phép sửa trực tiếp.
- Bộ lọc:
  - Ô nghi ngờ.
  - Sai công thức chuyển trang.
  - Chứng từ không cân.
  - Sai lệch đã xác nhận là do PDF gốc.
  - Dòng chưa xác nhận.
  - Dòng bị loại khỏi Excel.
- Nút **“Cảnh báo trước”** và **“Cảnh báo tiếp theo”**.
- Các thao tác cần thiết:
  - Thêm dòng bị sót.
  - Xóa dòng nhận trùng.
  - Tách/gộp diễn giải.
  - Đổi phân loại dòng.
  - Xác nhận dòng/trang đã đối chiếu.

## Phía dưới: Thông tin đối soát

Hiển thị bằng thuật ngữ kế toán:

- “Số trang trước chuyển sang”.
- “Tổng phát sinh trong trang”.
- “Cộng chuyển sang trang sau”.
- “Chênh lệch cần xử lý”.
- “Tổng Nợ/Có chứng từ”.
- “Tổng Nợ/Có toàn sổ”.

Trong chế độ chuyển đổi khớp PDF, mọi sửa đổi phải nhằm làm dữ liệu đúng với ảnh nguồn. Nếu nghi ngờ chính PDF bị sai, kế toán viên chọn **“Xác nhận sai lệch trên PDF gốc”** và giữ nguyên số liệu in trên PDF; không nhập một giá trị điều chỉnh khác PDF rồi gắn trạng thái khớp nguồn.

Sau mỗi lần sửa, phần mềm tự chạy lại các kiểm tra liên quan nhưng **không tự thay đổi dữ liệu để làm mất cảnh báo**.

---

# 8. Màn hình chính và tiến trình realtime

Giữ bố cục ba khu vực của mockup nhưng phải bổ sung chức năng chọn tệp và đơn giản hóa cách diễn đạt cho kế toán viên.

## Khu vực chọn dữ liệu

Trình bày theo ba bước rõ ràng:

1. Chọn dữ liệu:
   - Nút **“Chọn tệp PDF…”**, cho phép chọn một hoặc nhiều tệp.
   - Nút **“Chọn thư mục chứa PDF…”**.
   - Danh sách file đã chọn, cho phép bỏ file chọn nhầm và hiển thị tổng số file/tổng số trang.
2. Chọn nơi lưu Excel:
   - Tự đề xuất thư mục con `Excel_da_chuyen_doi` tại vị trí dữ liệu đầu vào.
   - Kế toán viên có thể đổi thư mục hoặc mở thư mục kết quả.
3. Nhấn **“Bắt đầu chuyển đổi”**.

Tùy chọn **“Xem trước 2 trang”** mặc định tắt, chỉ dùng khi cần kiểm tra mẫu trước.

## Khu vực xử lý

- **Bắt đầu chuyển đổi**.
- **Dừng xử lý**.
- **Kiểm tra dữ liệu**.
- **Mở Excel**.
- **Mở thư mục kết quả**.
- **Hướng dẫn sử dụng**.

Ngôn từ trên màn hình sử dụng thuật ngữ kế toán quen thuộc như chứng từ, bút toán, phát sinh Nợ/Có, đối chiếu và chênh lệch. Không hiển thị các từ kỹ thuật như OCR, confidence, exception, worker hoặc SHA-256 trong luồng sử dụng thông thường.

## Thông tin tiến trình

Cập nhật liên tục:

- Đồng hồ đã chạy, cập nhật mỗi giây bằng `QTimer` và đồng hồ đơn điệu, không phụ thuộc việc một trang đang xử lý lâu hay thay đổi giờ hệ thống.
- Thanh tiến trình tổng toàn bộ danh sách và tiến trình trang của file hiện tại.
- File đang xử lý.
- Trang hiện tại/tổng số trang.
- Công đoạn bằng ngôn từ dễ hiểu: đọc trang, nhận diện bảng, đọc dữ liệu, đối soát, tạo Excel, kiểm tra file Excel.
- Số trang hoàn thành.
- Số cảnh báo cần xử lý.
- Số giờ chạy chuyển đổi và thời gian kế toán viên đối chiếu thủ công được lưu riêng.

Công thức tiến trình:

```text
Tiến độ xử lý trang = Số trang đã hoàn thành / Tổng số trang × 100%
Tiến độ tổng = Số đơn vị công việc đã hoàn thành / Tổng đơn vị công việc của toàn lô × 100%
```

Đơn vị công việc của tiến trình tổng phải gồm cả xử lý trang, tạo Excel, mở lại và so sánh file; trọng số từng công đoạn được chốt sau PoC. **Tiến trình tổng chỉ đạt 100% sau khi Excel đã được lưu, mở lại và kiểm tra thành công.** Hoàn thành chuyển đổi tự động không đồng nghĩa với trạng thái “Đã đối chiếu khớp PDF”.

## Bảng kết quả từng file

- Tên PDF.
- Số trang đã xử lý/tổng số trang.
- Số dòng hạch toán.
- Tổng Nợ.
- Tổng Có.
- Chênh lệch Nợ–Có.
- Số cảnh báo trích xuất chưa xử lý.
- Trạng thái đối chiếu: **Chưa xử lý**, **Đang chuyển đổi**, **Cần đối chiếu**, **Đã đối chiếu khớp PDF**, **Đã dừng** hoặc **Lỗi – cần xử lý**.
- Kết quả kiểm tra kế toán riêng: **Chưa kiểm tra xong**, **Cân đối** hoặc **Có sai lệch trên PDF gốc**.
- Đồng hồ xử lý.
- Nút mở đối soát hoặc mở Excel.

## Dừng xử lý

- Không tắt ứng dụng đột ngột.
- Dừng sau trang/lượt xử lý đang chạy.
- Lưu dữ liệu các trang đã hoàn thành.
- Trạng thái hiển thị **“Đã dừng”**, không phải “Hoàn thành”.
- Có thể tiếp tục từ vị trí đã lưu nếu PDF và cấu hình không thay đổi.

Toàn bộ xử lý nặng chạy trong worker thread; worker chỉ gửi tín hiệu tiến trình và kết quả, không thao tác trực tiếp lên giao diện. Giao diện vẫn thao tác được, đồng hồ không bị đứng và chương trình không bị treo.

---

# 9. Lưu vết và xử lý lỗi

Mỗi ô dữ liệu cần lưu:

- File và trang nguồn.
- Tọa độ trên ảnh.
- Văn bản trích xuất gốc từ OCR hoặc text layer.
- Giá trị sau chuẩn hóa.
- Độ tin cậy OCR, nếu có.
- Giá trị trước và sau khi sửa.
- Trạng thái đã xem/đã xác nhận.
- Cảnh báo liên quan.

Mỗi thao tác thêm, xóa, sửa, tách, gộp, xác nhận trang hoặc xác nhận sai lệch nguồn đều ghi vào lịch sử.

Thông báo cho kế toán viên phải dễ hiểu, ví dụ:

> “Số tiền tại trang 12 có ký tự chưa rõ. Vui lòng đối chiếu ô được tô sáng với ảnh PDF.”

Thay vì:

> `OCR confidence threshold exception`.

Lỗi kỹ thuật chi tiết được ghi trong log riêng để hỗ trợ sửa lỗi, nhưng không hiển thị toàn bộ cho kế toán viên.

---

# 10. Các giai đoạn triển khai

| Giai đoạn | Nội dung | Kết quả bàn giao |
|---|---|---|
| **0. Chốt đặc tả** | Kiểm kê 5 PDF; chốt dòng cần loại, mẫu Excel, quy tắc giữ ô trống, độ chính xác số tiền, ngoại lệ đầu/cuối trang và cách xác nhận sai lệch nguồn | Đặc tả nghiệp vụ, mẫu Excel được duyệt |
| **1. PoC trích xuất và đóng gói** | Thử text layer/OCR trên trang rõ, mờ, nhiều dòng, đầu/cuối sổ; so sánh OpenCV/img2table; đóng gói thử one-file và chạy offline | Báo cáo chất lượng, kiến trúc cuối và một `.exe` thử nghiệm |
| **2. Bản thử 2 trang** | Chọn PDF → trích xuất → đối soát → sửa → xuất Excel nháp | Bản end-to-end để kế toán dùng thử |
| **3. Xử lý toàn sổ** | Nhiều file, nhiều trang, ghép chứng từ, lưu tiến trình | Bộ xử lý toàn bộ lô PDF |
| **4. Đối soát nâng cao** | Công thức trang, chuỗi trang, chứng từ, toàn sổ, sai lệch nguồn; màn hình đối chiếu | Quy trình xử lý cảnh báo hoàn chỉnh |
| **5. Hoàn thiện Excel** | Xuất nháp/cuối, định dạng, mở lại kiểm tra dữ liệu | Workbook đạt yêu cầu |
| **6. Nghiệm thu 5 sổ** | Chạy toàn bộ 2015–2019, sửa lỗi, đối chiếu theo chế độ nghiêm ngặt, đo hiệu năng | 5 file Excel đã đối chiếu |
| **7. Đóng gói bàn giao** | Hoàn thiện one-file, mô hình offline, hướng dẫn ngay trong ứng dụng; kiểm thử trên Windows sạch | Duy nhất `ChuyenSoNhatKyChung.exe` |

Thứ tự quan trọng: **làm bản thử 2 trang, thử đóng gói một `.exe` và được kế toán chấp nhận trước khi xây toàn bộ giao diện**, tránh hoàn thiện phần mềm rồi mới phát hiện OCR hoặc phương án đóng gói không phù hợp.

Ước tính triển khai có kiểm thử: khoảng **22–32 ngày làm việc**, chưa tính giờ làm việc của kế toán viên đối soát toàn bộ dữ liệu.

---

# 11. Chiến lược kiểm thử

## Dữ liệu chuẩn

Chọn tối thiểu 30 trang đại diện:

- Trang đầu và cuối sổ.
- Trang có nhiều chứng từ.
- Chứng từ nhiều dòng.
- Diễn giải dài.
- Chứng từ qua trang.
- Trang mờ hoặc hơi nghiêng.
- Trang có sai lệch hoặc bố cục khác.

Dữ liệu chuẩn phải được nhập và đối soát độc lập trước khi dùng đánh giá phần mềm. Bộ 30 trang dùng để kiểm thử động cơ trích xuất, **không thay thế việc xác nhận 100% trang của 5 sổ khi nghiệm thu dữ liệu cuối**.

## Nội dung kiểm thử

- Đọc đúng số tiền có dấu chấm/dấu phẩy, số âm, số trong ngoặc và số có phần thập phân nếu mẫu có.
- Giữ số `0` đầu của chứng từ/tài khoản; ô trống không bị chuyển thành `0`.
- Không tự lặp ngày hoặc số chứng từ vào dòng đang trống trên PDF.
- Không bỏ sót hoặc nhân đôi dòng.
- Phát hiện chứng từ không cân và chứng từ kéo dài qua trang.
- Áp dụng đúng quy tắc đầu/trang cuối; phát hiện đứt chuỗi chuyển trang, thiếu/trùng hoặc sai thứ tự trang.
- Không nối chuỗi chuyển trang giữa hai PDF khác nhau.
- Không tự sửa số tiền để cân.
- PDF gốc không cân nhưng dữ liệu trích xuất đúng vẫn có thể đạt **“Đã đối chiếu khớp PDF”**, nhưng phải giữ cảnh báo **“Có sai lệch trên PDF gốc”**.
- Không xuất file **“Đã đối chiếu khớp PDF”** khi còn cảnh báo trích xuất chưa xử lý hoặc trang chưa xác nhận.
- Chọn thư mục/một hoặc nhiều file đúng; không âm thầm bỏ file trùng nội dung ở các vị trí khác nhau.
- Tiến trình và đồng hồ đều cập nhật realtime; tiến trình tổng không đạt 100% trước khi Excel được lưu và mở lại kiểm tra.
- Dừng và tiếp tục không làm mất hoặc nhân đôi dữ liệu.
- File Excel đang mở thì báo lỗi rõ ràng, không ghi đè file cũ.
- Hoạt động đúng với tên file/thư mục tiếng Việt và đường dẫn dài.
- Chạy hết 5 sổ không tràn bộ nhớ.
- Chạy được khi ngắt Internet.
- Chép duy nhất file `.exe` sang máy Windows sạch: chạy được, không cần Python, không tải mô hình và thực hiện được toàn bộ luồng chuyển đổi.

Cần cố tình tạo các lỗi giả như thiếu một dòng, sai một chữ số, nhân đôi dòng hoặc sai dòng chuyển trang để kiểm tra phần mềm có phát hiện đúng không.

---

# 12. Tiêu chí nghiệm thu cuối cùng

1. 5/5 PDF được xử lý.
2. 100% trang có trạng thái rõ ràng và đã được kế toán viên xác nhận trong chế độ nghiêm ngặt trước khi xuất file cuối.
3. 100% dòng nguồn được phân loại.
4. Sheet nghiệp vụ có đúng 8 cột.
5. Không còn dòng chuyển trang, số trang, tiêu đề lặp hoặc thông tin dư thừa trong sheet nghiệp vụ.
6. Không thiếu hoặc thừa dòng sau đối soát; các ô trống trên PDF được giữ đúng, không tự điền dữ liệu suy ra.
7. 100% công thức chuyển trang áp dụng được có chênh lệch bằng `0`; nếu PDF gốc in sai, sai lệch đã được kế toán viên xác nhận là sai lệch nguồn và ghi đầy đủ tại sheet “Đối soát”.
8. Không còn ô nghi ngờ chưa xem.
9. Không còn cảnh báo trích xuất chưa xử lý khi xuất file cuối; cảnh báo kế toán của PDF gốc được quản lý riêng, không bị xóa hoặc tự sửa.
10. Tổng Nợ/Có và số dòng trong Excel khớp dữ liệu đã duyệt.
11. File Excel được mở lại và so sánh lại 100% giá trị, kiểu dữ liệu và thứ tự dòng với dữ liệu đã xác nhận.
12. Mọi sửa đổi và xác nhận đều có lịch sử.
13. Bộ bàn giao chỉ gồm một `ChuyenSoNhatKyChung.exe`; chép file này sang máy Windows sạch là chạy được, không cần cài Python hoặc tải thêm thành phần.
14. Không phát sinh kết nối gửi dữ liệu kế toán ra ngoài.
15. Chọn thư mục/file, đồng hồ realtime, tiến trình, dừng và tiếp tục đều được kiểm thử trên chính file `.exe` bàn giao.
16. Trạng thái đối chiếu PDF và kết quả kiểm tra kế toán được hiển thị riêng, không dùng điều kiện cân đối kế toán để thay thế việc kiểm tra độ khớp với nguồn.

---

# 13. Các phương án mặc định đã chốt

1. **Một PDF tạo một file Excel.**
2. **Giữ nguyên ô trống của ngày và số chứng từ trên từng dòng như PDF**, không tự lặp hoặc điền giá trị suy ra.
3. **Giữ xuống dòng trong diễn giải.**
4. Workbook gồm **Nhật ký chung, Đối soát, Thông tin**.
5. Muốn công nhận “khớp 100%” thì áp dụng **chế độ nghiêm ngặt: xác nhận từng trang**, không chỉ xử lý các cảnh báo.
6. Nếu PDF quá mờ, thiếu trang hoặc không thể xác nhận dữ liệu nguồn thì giữ trạng thái **“Cần đối chiếu”**.
7. Nếu PDF gốc không cân hoặc in sai dòng chuyển trang nhưng dữ liệu trích xuất đã được xác nhận khớp nguồn thì vẫn có thể đạt **“Đã đối chiếu khớp PDF”**, nhưng phải giữ riêng cảnh báo kế toán tại sheet “Đối soát”.
8. Các dòng chuyển trang và thông tin bị loại chỉ được giữ để kiểm soát tại sheet **“Đối soát”**, không đưa vào sheet **“Nhật ký chung”**.
9. Bàn giao **duy nhất một `ChuyenSoNhatKyChung.exe`**, chạy offline, không cần cài đặt.

Bước triển khai đầu tiên nên là **PoC trích xuất, đối soát 2 trang và đóng gói thử một `.exe`**, sau đó đưa anh hoặc kế toán viên kiểm tra trước khi phát triển toàn bộ ứng dụng.
