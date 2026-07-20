---
name: plan-skill
description: 'Những quy tắt bắt buộc khi lập kế hoạch dự án.'
argument-hint: tuân thủ các quy tắc đã đề ra.'
user-invocable: true
---

# Với mỗi task được giao, hãy tuân thủ các quy tắc sau:
- luôn tuân theo quy trình code sau:

  1. lên một file plan rõ ràng và chi tiết vào folder `plans` với tên file là `plan-{task_name}.md`

  2. trong file plan, hãy mô tả chi tiết các bước cần thực hiện để hoàn thành task, bao gồm:
     - mục tiêu của task.
     - các bước cụ thể cần thực hiện.
     - thời gian dự kiến cho mỗi bước.
     - các tài nguyên cần thiết (nếu có).

  3. Phải có mô tả chi tiết plan đó cần các skill nào để thực hiện, và nếu có thể hãy gợi ý các skill cần thiết để hoàn thành task đó, hiện tại ta sẽ có các skill sau: backend-skill, frontend-skill, testing-skill, documentation-skill, logging-skill.

  4. Khi code theo plan phải tuẩn thủ đúng theo quy trình sau:
  - Với mỗi phase của plan phải đi theo quy trình: đọc skill cần thiết, thực hiện phase đó, testing phase đó, ghi lại documentation cho phase đó, logging lại quá trình thực hiện phase đó, phải đảm bảo rằng phase đó đã pass theo đúng testing-skill thì mới tiếp tục.
  - Phải làm lần lượt hết tất cả các phase cho đến khi hoàn thành task, không được bỏ qua bất kỳ phase nào thì mới được coi là hoàn thành task đó.

  5. Nếu có bất kỳ thắc mắc nào về task hoặc quy trình, hãy hỏi ngay để được giải đáp trước khi bắt đầu thực hiện task, tránh việc làm sai quy trình hoặc bỏ qua các bước quan trọng.

  6. Sau khi hoàn thành task, hãy tổng kết lại quá trình thực hiện, những khó khăn gặp phải và cách giải quyết vào file documentation của task đó (đọc kỹ quy tắc của documentation-skill để biết cách viết documentation đúng chuẩn).

  7. Sau khi hoàn thành task, hãy ghi lại log chi tiết quá trình thực hiện vào file logging của task đó (đọc kỹ quy tắc của logging-skill để biết cách viết log đúng chuẩn).

  8. Sau khi hoàn thành task hãy push dự án lên repository theo đúng push-code-skill đã đề ra, đảm bảo rằng code đã được review và pass tất cả các test trước khi push lên repository.
