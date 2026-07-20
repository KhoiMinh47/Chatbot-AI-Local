import asyncio
import httpx
import time
import statistics
import argparse
import sys
import math
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class RequestResult:
    success: bool
    latency: float
    error: str = ""

class ProgressBar:
    def __init__(self, total: int):
        self.total = total
        self.completed = 0
        self.start_time = time.time()
        self.lock = asyncio.Lock()

    async def update(self):
        async with self.lock:
            self.completed += 1
            progress = self.completed / self.total
            bar_len = 30
            filled_len = int(round(bar_len * progress))
            bar = '=' * filled_len + '-' * (bar_len - filled_len)

            elapsed = time.time() - self.start_time
            rate = self.completed / elapsed if elapsed > 0 else 0

            sys.stdout.write(f'\rTiến độ: [{bar}] {self.completed}/{self.total} | Tốc độ: {rate:.1f} req/s | Thời gian: {elapsed:.1f}s')
            sys.stdout.flush()
            if self.completed == self.total:
                sys.stdout.write('\n\n')

async def make_request(client: httpx.AsyncClient, url: str, payload: dict, token: str, semaphore: asyncio.Semaphore, pbar: ProgressBar) -> RequestResult:
    """Thực hiện request tới API Backend và tính thời gian phản hồi (End-to-End)."""
    async with semaphore:
        start_time = time.perf_counter()

        headers = {}
        cookies = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            cookies["access_token"] = token

        try:
            response = await client.post(url, json=payload, headers=headers, cookies=cookies)
            response.raise_for_status()
            # Đọc `.text` đảm bảo đã tải toàn bộ response về máy trước khi chốt giờ
            _ = response.text
        except Exception as e:
            end_time = time.perf_counter()
            await pbar.update()
            return RequestResult(success=False, latency=end_time - start_time, error=str(e))

        end_time = time.perf_counter()
        latency = end_time - start_time

        await pbar.update()
        return RequestResult(
            success=True,
            latency=latency
        )

def calc_percentile(data: List[float], percent: float) -> float:
    """Tính các bách phân vị."""
    if not data:
        return 0.0
    k = (len(data) - 1) * percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[int(f)] * (c - k) + data[int(c)] * (k - f)

def print_metrics(results: List[RequestResult], total_time: float, concurrency: int):
    """In báo cáo kết quả."""
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print("=" * 60)
    print("🚀 BÁO CÁO BENCHMARK BACKEND API (RAG Chatbot)")
    print("=" * 60)
    print(f"🔹 Tổng số Requests      : {len(results)}")
    print(f"🔹 Requests Thành công   : {len(successful)}")
    print(f"🔹 Requests Thất bại     : {len(failed)}")
    print(f"🔹 Mức độ đồng thời (C)  : {concurrency}")
    print(f"🔹 Tổng thời gian (Wall) : {total_time:.2f} s")
    print("-" * 60)

    if not successful:
        print("❌ Cảnh báo: Tất cả request đều thất bại.")
        if failed:
            print(f"Lỗi tiêu biểu: {failed[0].error}")
        return

    # Tính system throughput
    throughput_req = len(successful) / total_time

    print(f"📊 THÔNG LƯỢNG (SYSTEM THROUGHPUT):")
    print(f"  • Tốc độ xử lý (QPS)       : {throughput_req:.2f} requests/giây")
    print(f"  • Chịu tải đồng thời       : {concurrency} users")
    print("-" * 60)

    def format_stats(data_list, unit="ms", multiplier=1000.0):
        if not data_list:
            return "N/A"
        arr = sorted([d * multiplier for d in data_list])
        mean_val = statistics.mean(arr)
        p50 = calc_percentile(arr, 0.50)
        p90 = calc_percentile(arr, 0.90)
        p99 = calc_percentile(arr, 0.99)
        return (f"Trung bình: {mean_val:6.2f} {unit} | P50: {p50:6.2f} {unit} | "
                f"P90: {p90:6.2f} {unit} | P99: {p99:6.2f} {unit}")

    latencies = [r.latency for r in successful]

    print(f"⏱️  ĐỘ TRỄ (END-TO-END LATENCY):")
    print(f"  Tổng thời chạy của toàn bộ Pipeline (Bao gồm Retriever + Prompting + LLM Generation):")
    print(f"    👉 {format_stats(latencies, 's', 1.0)}")

    print("=" * 60)
    print("💡 Lưu ý khi Viết Blog:")
    print("- Backend API thường có độ trễ lớn hơn khá nhiều so với vLLM đơn thuần vì phải cõng")
    print("  thêm phần logic xử lý RAG (Tìm kiếm Vector DB, Cross-Encoder, tạo Prompt).")
    print("- Chỉ số QPS (Requests/s) ở Backend mới chính là sức mạnh phục vụ ứng dụng thực tế,")
    print("  chứ không phải chỉ là việc LLM nhả chữ nhanh hay chậm.")
    print("=" * 60)

async def main():
    parser = argparse.ArgumentParser(description="Khung Benchmark Backend API RAG")
    parser.add_argument("--url", type=str, default="http://localhost:9000/api/v1/rags/rag-contract-fast", help="URL của Backend API")
    parser.add_argument("--token", type=str, default="", help="JWT Bearer Token để Authorization Backend")
    parser.add_argument("--model", type=str, default="google/gemma-4-E4B-it", help="Tên model đang được deploy")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Số lượng kết nối đồng thời")
    parser.add_argument("-n", "--num-requests", type=int, default=30, help="Tổng Số requests để benchmark")
    args = parser.parse_args()

    # Query mô phỏng đa dạng
    sample_queries = [
        "Tóm tắt hợp đồng có trên hệ thống?",
        "Quy trình xử lý vi phạm trong trường hợp nhân viên đi trễ là gì?",
        "Giải mã điều khoản thanh toán trong quy định.",
        "Mức phạt nếu công ty vi phạm hợp đồng lao động?",
        "Tôi muốn hỏi về chính sách bảo mật."
    ]

    print(f"🚀 Bắt đầu quá trình Benchmark Backend API...")
    print(f"🔗 URL         : {args.url}")
    print(f"⚙️  Tổng request: {args.num_requests}")
    print(f"👥 Đồng thời   : {args.concurrency}\n")

    # Cấu hình limits lớn hơn để HTTPX không bị nghẽn ở pool connection
    limits = httpx.Limits(max_connections=args.concurrency + 10, max_keepalive_connections=args.concurrency)
    timeout = httpx.Timeout(300.0)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        semaphore = asyncio.Semaphore(args.concurrency)
        pbar = ProgressBar(args.num_requests)

        tasks = []
        for i in range(args.num_requests):
            query = sample_queries[i % len(sample_queries)]
            payload = {
                # session_id = -1 nghĩa là yêu cầu tạo session mới trong DB backend
                "session_id": -1,
                "user_input": query,
                "model_name": args.model
            }
            tasks.append(make_request(client, args.url, payload, args.token, semaphore, pbar))

        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end_time = time.perf_counter()

    print_metrics(results, end_time - start_time, args.concurrency)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Đã huỷ benchmark bởi người dùng.")
