# Sitemap Checker

Công cụ Python quét sitemap website: nhập vào 1 URL sitemap (thường là
`sitemap_index.xml`), tool sẽ tự động phát hiện và truy cập các sitemap con
lồng bên trong, sau đó thống kê số lượng URL của từng sitemap.

## 1. Yêu cầu

- Python 3.7 trở lên
- Thư viện `requests`

## 2. Cài đặt

Bước 1: Mở terminal, di chuyển vào thư mục chứa tool:

```bash
cd /home/tungnt/Documents/tungnt/scan-url
```

Bước 2: (Khuyến khích) Tạo môi trường ảo để không ảnh hưởng tới Python hệ
thống:

```bash
python3 -m venv venv
source venv/bin/activate
```

Bước 3: Cài thư viện cần thiết:

```bash
pip install -r requirements.txt
```

Nếu không muốn dùng venv, có thể bỏ qua bước 2 và cài trực tiếp:

```bash
pip install requests
```

## 3. Cách chạy

Cú pháp chung:

```bash
python3 sitemap_checker.py <URL_SITEMAP> [--timeout SECONDS] [--csv FILE.csv]
```

### Ví dụ cơ bản

```bash
python3 sitemap_checker.py https://example.com/sitemap_index.xml
```

Kết quả in ra terminal dạng bảng:

```
Sitemap                          So luong URL
---------------------------------------------
post-sitemap.xml                           91
page-sitemap.xml                            6
attachment-sitemap.xml                     483
product-sitemap.xml                        20
category-sitemap.xml                        3
post_tag-sitemap.xml                       69
product_cat-sitemap.xml                    16
product_tag-sitemap.xml                    11
---------------------------------------------
Tong                                       699

Luu y: attachment-sitemap chiem 483/699 URL (~69%).
```

### Tăng thời gian chờ (timeout)

Dùng khi website phản hồi chậm, mặc định 15 giây:

```bash
python3 sitemap_checker.py https://example.com/sitemap_index.xml --timeout 30
```

### Xuất kết quả ra file CSV

```bash
python3 sitemap_checker.py https://example.com/sitemap_index.xml --csv result.csv
```

File `result.csv` sẽ có các cột: `sitemap, url, count, error`.

### Đưa vào trang web thường (tool tự tìm sitemap)

Nếu không biết URL sitemap chính xác, chỉ cần đưa domain trang web (không kết
thúc bằng `.xml`), tool sẽ tự động tìm theo thứ tự:

1. Đọc `robots.txt` (vd `https://example.com/robots.txt`), gom **tất cả** các
   dòng `Sitemap: ...` (một site có thể khai báo nhiều sitemap gốc khác nhau)
   rồi quét lần lượt từng cái.
2. Nếu `robots.txt` không khai báo sitemap nào, thử lần lượt các đường dẫn phổ
   biến: `/sitemap_index.xml`, `/sitemap.xml`, `/sitemap-index.xml`,
   `/wp-sitemap.xml`, `/sitemapindex.xml` — dùng ngay cái đầu tiên tồn tại.
3. Nếu tất cả sitemap lấy từ `robots.txt` đều lỗi khi truy cập (ví dụ
   `robots.txt` khai báo nhầm sang domain khác không còn tồn tại), tool tự
   động thử tiếp các đường dẫn phổ biến ngay trên domain gốc trước khi báo
   không tìm thấy sitemap nào.

```bash
python3 sitemap_checker.py https://example.com
```

Nếu muốn tắt tính năng này (ví dụ URL của bạn không đuôi `.xml` nhưng vẫn là
sitemap thật), thêm cờ `--no-discover`:

```bash
python3 sitemap_checker.py https://example.com/my-custom-sitemap --no-discover
```

### Quét sitemap đơn (không phải sitemap index)

Tool tự nhận diện — nếu URL truyền vào là một `urlset` (sitemap thường, không
có sitemap con) thì sẽ in luôn số lượng URL của chính nó, không cần đệ quy.

```bash
python3 sitemap_checker.py https://example.com/post-sitemap.xml
```

## 4. Cách hoạt động

0. (Nếu URL không kết thúc bằng `.xml` và không tắt bằng `--no-discover`) Tự
   động tìm sitemap: đọc `robots.txt` trước, nếu không có thì thử các đường
   dẫn phổ biến (`/sitemap.xml`, `/sitemap_index.xml`, ...).
1. Tải nội dung XML tại URL được cung cấp (hoặc URL vừa tự tìm được).
2. Kiểm tra thẻ gốc:
   - Nếu là `<sitemapindex>` → lấy danh sách các `<loc>` sitemap con, rồi gọi
     đệ quy để xử lý từng sitemap con (áp dụng cho cả trường hợp lồng nhiều
     cấp).
   - Nếu là `<urlset>` → đếm số thẻ `<url>` bên trong, đây chính là số lượng
     URL của sitemap đó.
3. Gom toàn bộ kết quả lại, in bảng thống kê + tổng cộng.
4. Nếu có sitemap con lỗi (404, timeout, sai định dạng...), tool vẫn tiếp tục
   xử lý các sitemap còn lại và ghi chú lỗi thay vì dừng toàn bộ chương trình.
5. Tự động cảnh báo nếu `attachment-sitemap` (sitemap đính kèm/media) chiếm tỷ
   trọng lớn trong tổng số URL — đây là dấu hiệu cần xem xét loại bỏ khỏi
   sitemap để tối ưu SEO.

## 5. Xử lý sự cố thường gặp

- **Lỗi `ModuleNotFoundError: No module named 'requests'`**: chạy lại
  `pip install -r requirements.txt` (nhớ kích hoạt venv nếu có tạo ở bước 2).
- **Lỗi timeout**: tăng giá trị `--timeout`, hoặc kiểm tra lại URL/mạng.
- **Kết quả count = 0 kèm `[ERROR: ...]`**: URL sitemap con bị lỗi (404, XML
  sai định dạng...) — xem nội dung lỗi được in kèm để biết nguyên nhân cụ thể.
- **Sitemap yêu cầu User-Agent riêng hoặc bị chặn**: tool đã tự set User-Agent
  giả lập trình duyệt, nhưng nếu vẫn bị chặn (403), có thể cần thêm cookie/
  header riêng — liên hệ để bổ sung tùy chỉnh.
