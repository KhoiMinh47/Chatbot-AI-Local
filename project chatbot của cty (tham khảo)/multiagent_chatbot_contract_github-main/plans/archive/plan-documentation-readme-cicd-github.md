# PLAN: Chuẩn hóa Documentation, README, License, CI/CD và Push GitHub

- Ngày lập kế hoạch: 2026-05-13
- Task name: documentation-readme-cicd-github
- Mục tiêu tổng: Rà soát toàn bộ tài liệu hiện có, viết lại tài liệu tiếng Việt rõ ràng dễ hiểu, thiết kế lại README theo template đã cung cấp, chuẩn hóa cấu trúc đặt tên tài liệu, bổ sung license MIT, tăng độ nghiêm ngặt CI/CD theo hướng production, và push lại GitHub theo quy trình chuẩn.

## 1) Mục tiêu chi tiết

1. Đọc lại toàn bộ docs, plan, README hiện tại để xác định nội dung trùng lặp, thiếu, lỗi thời.
2. Viết lại bộ tài liệu tiếng Việt theo hướng rõ ràng, có cấu trúc, dễ tra cứu cho người mới.
3. Thiết kế lại README gốc theo template người dùng cung cấp (chuẩn banner, mục lục, quick start, API, docs index).
4. Đặt tên file/tên thư mục tài liệu theo chuẩn thống nhất và tách nhóm tài liệu theo chủ đề (không dồn tất cả vào một chỗ khó tìm).
5. Bổ sung file LICENSE MIT cho repository và cập nhật phần license trong README.
6. Viết lại/siết chặt CI/CD: lint, test, security checks, build checks, artifact policy, release gates.
7. Push code với commit message rõ ràng, có mô tả, đảm bảo pass test/CI trước khi đẩy.

## 2) Phạm vi công việc

- In scope:
  - README tổng dự án.
  - Tài liệu trong docs và plan có liên quan trực tiếp đến mô tả dự án/vận hành.
  - Chuẩn hóa taxonomy thư mục tài liệu.
  - License MIT.
  - GitHub Actions workflows và tiêu chuẩn kiểm tra chất lượng.
  - Quy trình commit/push theo push-code-skill.
- Out of scope:
  - Refactor logic nghiệp vụ backend/frontend không liên quan trực tiếp tài liệu/CI.
  - Thay đổi kiến trúc hệ thống lớn ngoài nội dung đã có.

## 3) Skill bắt buộc và skill gợi ý

### 3.1 Skill bắt buộc theo quy trình

1. plan-skill: lập kế hoạch phase rõ ràng, tuần tự, có thời lượng và tiêu chí pass.
2. documentation-skill: viết doc đúng chuẩn, có thời gian, tóm tắt trọng tâm, dọn dẹp tài liệu cũ.
3. logging-skill: ghi log tiến trình task vào logs, có timestamp, ngắn gọn trọng tâm.
4. push-code-skill: rà soát CI/CD, test nghiêm ngặt, commit/push rõ ràng.
5. backend-skill: chuẩn hóa tài liệu backend và kiểm thử pipeline backend trong CI.
6. frontend-skill: chuẩn hóa tài liệu frontend và kiểm thử frontend trong CI.

### 3.2 Skill gợi ý bổ sung

1. testing-skill (đề xuất tạo mới): checklist test chuẩn cho mỗi phase, tiêu chí pass/fail, test matrix.
2. security-skill (đề xuất): SAST, dependency audit, secret scan, policy cho PR.
3. devops-cicd-skill (đề xuất): chiến lược cache, matrix build, release tagging, rollback strategy.

## 4) Quy trình bắt buộc cho mỗi phase (gate không được bỏ qua)

Với mỗi phase phải thực hiện đúng thứ tự:

1. Đọc skill cần thiết cho phase.
2. Thực hiện công việc của phase.
3. Testing phase theo checklist (lint/test/build/link check nếu áp dụng).
4. Cập nhật documentation cho phase.
5. Ghi log phase vào logs với thời gian và kết quả.
6. Chỉ khi phase pass mới chuyển phase tiếp theo.

## 5) Kế hoạch thực thi theo phase

## Phase 0 - Khởi động và baseline

- Mục tiêu: Chốt phạm vi, tạo baseline hiện trạng docs/README/CI/CD trước khi chỉnh sửa.
- Skill: plan-skill, documentation-skill, logging-skill.
- Công việc:
  1. Inventory toàn bộ file docs, plan, README, workflow CI/CD.
  2. Chụp baseline: danh sách file, quality gaps, duplicate, outdated.
  3. Chốt quy ước đặt tên và phân nhóm thư mục tài liệu.
- Testing:
  - Kiểm tra mapping file hiện tại đầy đủ 100% (không bỏ sót nhóm chính).
  - Review chéo danh sách inventory với cấu trúc repo thực tế.
- Documentation output:
  - Tạo báo cáo baseline và checklist migration.
- Logging output:
  - Log mốc bắt đầu task, phạm vi, baseline findings.
- Thời gian dự kiến: 0.5 ngày.
- Tài nguyên:
  - Quyền đọc toàn bộ repo.
  - Mẫu README người dùng cung cấp.

## Phase 1 - Thiết kế taxonomy tài liệu và chuẩn naming

- Mục tiêu: Định nghĩa cấu trúc thư mục tài liệu dễ tìm, dễ mở rộng.
- Skill: documentation-skill, backend-skill, frontend-skill.
- Công việc:
  1. Thiết kế cây thư mục docs theo domain.
  2. Đề xuất quy tắc đặt tên file: lowercase-kebab-case, prefix theo nhóm khi cần.
  3. Lập mapping di chuyển file cũ -> file mới.
- Cấu trúc đề xuất:
  - docs/overview/
  - docs/architecture/
  - docs/backend/
  - docs/frontend/
  - docs/pipeline/
  - docs/deployment/
  - docs/operations/
  - docs/api/
  - docs/history/
  - docs/adr/ (nếu có quyết định kiến trúc)
- Testing:
  - Validate không có tên trùng, không có đường dẫn mơ hồ.
  - Link nội bộ không gãy sau đổi tên (link check).
- Documentation output:
  - Guideline đặt tên + tài liệu taxonomy.
- Logging output:
  - Log quyết định taxonomy và lý do.
- Thời gian dự kiến: 0.5 ngày.
- Tài nguyên:
  - Danh sách tài liệu hiện có.
  - Công cụ kiểm tra link markdown.

## Phase 2 - Viết lại bộ tài liệu tiếng Việt đầy đủ, rõ ràng

- Mục tiêu: Chuẩn hóa nội dung tài liệu dự án bằng tiếng Việt theo cấu trúc mới.
- Skill: documentation-skill, backend-skill, frontend-skill.
- Công việc:
  1. Đọc và hợp nhất nội dung docs + plan + README hiện có.
  2. Viết lại theo chuẩn: mục tiêu, luồng hệ thống, thành phần, vận hành, troubleshooting.
  3. Tách nội dung theo folder mới, thêm docs index điều hướng.
  4. Loại bỏ/đánh dấu tài liệu lỗi thời.
- Testing:
  - Soát chính tả/thuật ngữ nhất quán.
  - Kiểm tra khả năng onboarding: người mới đọc có chạy được hệ thống theo docs.
  - Markdown lint + link validation.
- Documentation output:
  - Bộ docs tiếng Việt mới đầy đủ.
  - File chỉ mục docs tổng.
- Logging output:
  - Log danh sách file đã viết mới/sửa/xóa, lý do thay đổi.
- Thời gian dự kiến: 1.5 ngày.
- Tài nguyên:
  - SMEs kỹ thuật backend/frontend (nếu cần xác minh nội dung).
  - Bộ script/check markdown lint.

## Phase 3 - Thiết kế lại README theo template người dùng

- Mục tiêu: README chuyên nghiệp, rõ ràng, nhất quán branding theo template được gửi.
- Skill: documentation-skill, frontend-skill, push-code-skill.
- Công việc:
  1. Áp dụng cấu trúc template: banner, value proposition, quick start, API, docs index.
  2. Điều chỉnh nội dung để phản ánh đúng repo hiện tại.
  3. Đồng bộ section License, CI status, architecture summary.
- Testing:
  - Kiểm tra hiển thị markdown trên GitHub.
  - Kiểm tra toàn bộ link nội bộ README.
  - Kiểm tra câu lệnh quick start có thể chạy.
- Documentation output:
  - README mới phiên bản chuẩn.
- Logging output:
  - Log các section thay đổi lớn và rationale.
- Thời gian dự kiến: 0.75 ngày.
- Tài nguyên:
  - Template README mẫu.
  - Badge/link chuẩn của repository.

## Phase 4 - Bổ sung license MIT cho repository

- Mục tiêu: Thêm đầy đủ thông tin pháp lý license MIT.
- Skill: documentation-skill, push-code-skill.
- Công việc:
  1. Thêm file LICENSE (MIT full text).
  2. Cập nhật README và docs index để phản ánh license.
  3. Kiểm tra không xung đột với thành phần có license khác.
- Testing:
  - Kiểm tra GitHub nhận diện license tự động.
  - Kiểm tra metadata/license references trong docs.
- Documentation output:
  - Mục License cập nhật đồng bộ.
- Logging output:
  - Log thời điểm thêm license, phạm vi ảnh hưởng.
- Thời gian dự kiến: 0.25 ngày.
- Tài nguyên:
  - Danh sách dependency và license tương ứng.

## Phase 5 - Viết lại CI/CD nghiêm ngặt chuẩn production

- Mục tiêu: Thiết lập pipeline CI/CD chặt chẽ, giảm rủi ro trước merge/release.
- Skill: push-code-skill, backend-skill, frontend-skill, testing-skill (đề xuất).
- Công việc:
  1. Chuẩn hóa workflow CI:
     - backend: lint + unit/integration test + coverage threshold.
     - frontend: lint + test + build.
     - markdown/doc lint + link check.
     - dependency audit + secret scan + SAST cơ bản.
  2. Chuẩn hóa workflow CD:
     - release điều kiện (tag/branch rules).
     - build artifact/image có checksum.
     - gate chỉ deploy khi CI pass hoàn toàn.
  3. Thiết lập quality gates:
     - required checks cho PR.
     - branch protection khuyến nghị.
     - concurrency control và cancel in-progress khi push mới.
  4. Tối ưu hiệu năng pipeline:
     - cache dependency.
     - matrix strategy khi cần.
- Testing:
  - Dry-run workflow trên PR test branch.
  - Fail-case tests: cố ý tạo lỗi lint/test để xác minh gate chặn merge.
  - Verify artifact và điều kiện trigger release.
- Documentation output:
  - Tài liệu CI/CD runbook và policy.
- Logging output:
  - Log kết quả từng workflow test và gate status.
- Thời gian dự kiến: 1.5 ngày.
- Tài nguyên:
  - GitHub Actions permissions.
  - Secrets/variables cho release nếu có.

## Phase 6 - Hoàn tất documentation task + logging task + push GitHub

- Mục tiêu: Chốt hồ sơ task đầy đủ và push đúng chuẩn.
- Skill: documentation-skill, logging-skill, push-code-skill.
- Công việc:
  1. Viết báo cáo tổng kết task: đã làm gì, khó khăn, cách giải quyết.
  2. Ghi log cuối task có timeline rõ ràng.
  3. Chạy full test/lint/checklist cuối cùng.
  4. Commit theo chuẩn message rõ ràng + mô tả chi tiết.
  5. Push lên GitHub và xác nhận CI pass.
- Testing:
  - Full local check + remote CI pass.
  - Verify commit history và nội dung PR rõ ràng.
- Documentation output:
  - File tổng kết task trong docs.
- Logging output:
  - File log task trong logs.
- Thời gian dự kiến: 0.5 ngày.
- Tài nguyên:
  - Quyền push branch/repo.
  - Chính sách branch protection.

## 6) Tổng thời gian dự kiến

- Tổng effort: 5.5 ngày làm việc.
- Buffer rủi ro: 0.5 ngày.
- Tổng timeline đề xuất: 6 ngày làm việc.

## 7) Tiêu chí hoàn thành (Definition of Done)

1. Có cấu trúc tài liệu mới, dễ tìm, naming chuẩn, link không gãy.
2. Bộ docs tiếng Việt đầy đủ và nhất quán.
3. README mới theo template đã gửi, phản ánh đúng dự án.
4. Có file LICENSE MIT và hiển thị đúng trong README/GitHub.
5. CI/CD nghiêm ngặt đã chạy pass; có quality gate rõ ràng.
6. Có file tổng kết documentation của task.
7. Có file logging của task theo chuẩn timestamp.
8. Code đã commit/push và qua review + test.

## 8) Rủi ro chính và phương án giảm thiểu

1. Rủi ro: tài liệu cũ mâu thuẫn với code hiện tại.
   - Giảm thiểu: ưu tiên xác minh bằng source code và workflow thực tế.
2. Rủi ro: CI/CD quá chặt làm tăng thời gian chạy.
   - Giảm thiểu: áp dụng cache, chia job hợp lý, song song hóa.
3. Rủi ro: thiếu testing-skill chính thức.
   - Giảm thiểu: dùng checklist test cụ thể trong plan này và đề xuất tạo testing-skill ngay sau task.
4. Rủi ro: thiếu quyền repo cho branch protection/secrets.
   - Giảm thiểu: chuẩn bị danh sách yêu cầu quyền ngay từ đầu.

## 9) Câu hỏi cần xác nhận trước khi triển khai thực thi (theo rule #5)

- README mới sẽ dùng tiếng Việt hoàn toàn hay song ngữ Việt-Anh?
Trả lời: Tiếng Việt.

- Phạm vi docs cần viết lại là toàn bộ repository hay ưu tiên backend/frontend/pipeline trước?
Trả lời: Toàn bộ, có thể chia phase nếu khối lượng quá lớn.

- CI/CD nghiêm ngặt mong muốn bao gồm security scan nào là bắt buộc (ví dụ: dependency audit, secret scan, SAST)?
Trả lời: Tất cả đều bắt buộc.

- Push trực tiếp lên nhánh chính hay qua nhánh feature + PR?
Trả lời: Nhánh chính.

- License MIT áp dụng toàn bộ repo hay chỉ một phần module cụ thể?
Trả lời: Toàn repo.

## 10) Deliverables dự kiến

1. Kế hoạch thực thi chi tiết (file hiện tại).
2. Bộ docs tiếng Việt tái cấu trúc theo taxonomy mới.
3. README mới theo template.
4. LICENSE MIT.
5. Bộ workflow CI/CD mới hoặc được siết chặt.
6. Báo cáo tổng kết task trong docs.
7. Log task trong logs.
