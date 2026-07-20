---
name: logging-skill
description: 'Những quy tắt bắt buộc khi ghi và quản lý logs cho dự án (logs của phiên làm việt chứ không phải logs debug cho code)'
argument-hint: 'tuân thủ các quy tắc đã đề ra.'
user-invocable: true
---

# logging-skill
Những quy tắt bắt buộc khi ghi và quản lý logs cho dự án:

## Lưu trữ
- Tất cả logs đều phải lưu trong folder tổng là logs ở project tổng.
- Mỗi task phải ghi lại một logs có chia folder rõ ràng từng loại khác nhau và sắp xếp gọn gàn dễ hiểu.
- Nếu các logs có liên quan đến nhau bạn có thể gom vào chung 1 file và tóm tắt lại.

## Tóm tắt
- Mỗi file log không quá dài chỉ tóm tắt lại đúng những điểm quan trọng, trọng tâm.
- Luôn quét lại hết các file doc và tóm tắt, clean, xóa, sửa nếu cần sau mỗi task.


## Format
- Log phải có thời gian rõ ràng.