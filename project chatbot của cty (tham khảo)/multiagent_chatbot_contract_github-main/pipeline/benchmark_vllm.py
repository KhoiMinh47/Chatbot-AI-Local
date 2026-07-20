import asyncio
import httpx
import time
import statistics
import json
import argparse
import sys
import math
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class RequestResult:
    success: bool
    latency: float
    ttft: Optional[float] = None  # Time to First Token
    tpot: Optional[float] = None  # Time per Output Token
    single_req_tps: Optional[float] = None # Tokens per second cho 1 request đơn
    input_tokens: int = 0
    output_tokens: int = 0
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

async def fetch_model_name(client: httpx.AsyncClient, base_url: str) -> str:
    """Tự động lấy tên model đang chạy trên vLLM server."""
    try:
        response = await client.get(f"{base_url}/v1/models", timeout=10.0)
        response.raise_for_status()
        data = response.json()
        if data and "data" in data and len(data["data"]) > 0:
            return data["data"][0]["id"]
    except Exception as e:
        print(f"\n⚠️ Cảnh báo: Không thể lấy danh sách model tự động ({e}).")
    return "default-model"

async def make_request(client: httpx.AsyncClient, base_url: str, model: str, prompt: str, semaphore: asyncio.Semaphore, pbar: ProgressBar) -> RequestResult:
    """Thực hiện một request stream đến vLLM và đo đạc các số liệu."""
    async with semaphore:
        start_time = time.perf_counter()
        first_token_time = None
        output_tokens = 0
        input_tokens = 0

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": 512,
            "temperature": 0.0
        }

        try:
            async with client.stream("POST", f"{base_url}/v1/chat/completions", json=payload) as response:
                response.raise_for_status()

                manual_output_tokens = 0
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Track TTFT (Time to First Token)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if delta.get("content"):
                            if first_token_time is None:
                                first_token_time = time.perf_counter()
                            manual_output_tokens += 1

                    # Lấy thông tin về tokens do chuẩn OpenAI API (vLLM return) trả ra
                    if "usage" in data and data["usage"] is not None:
                        input_tokens = data["usage"].get("prompt_tokens", 0)
                        output_tokens = data["usage"].get("completion_tokens", 0)

        except Exception as e:
            end_time = time.perf_counter()
            await pbar.update()
            return RequestResult(success=False, latency=end_time - start_time, error=str(e))

        end_time = time.perf_counter()
        latency = end_time - start_time
        ttft = (first_token_time - start_time) if first_token_time else None

        # Nếu model không trả về object usage (không hỗ trợ `stream_options`) -> dùng tham số dự phòng ước tính
        if output_tokens == 0:
            output_tokens = manual_output_tokens
            # Việc tính input token có thể không chính xác tuyệt đối mà ước tính theo độ dài nếu không có `usage`
            input_tokens = len(prompt) // 4

        # Tính toán TPOT (Time Per Output Token)
        tpot = None
        if ttft is not None and output_tokens > 1:
            tpot = (latency - ttft) / (output_tokens - 1)
        elif output_tokens == 1:
            tpot = latency - ttft

        single_req_tps = None
        if tpot is not None and tpot > 0:
            single_req_tps = 1.0 / tpot
        elif latency > 0 and output_tokens > 0:
            single_req_tps = output_tokens / latency

        await pbar.update()
        return RequestResult(
            success=True,
            latency=latency,
            ttft=ttft,
            tpot=tpot,
            single_req_tps=single_req_tps,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

def calc_percentile(data: List[float], percent: float) -> float:
    """Hàm phụ trợ tính bách phân vị."""
    if not data:
        return 0.0
    k = (len(data) - 1) * percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[int(f)] * (c - k) + data[int(c)] * (k - f)

def print_metrics(results: List[RequestResult], total_time: float, concurrency: int):
    """Tính toán và in báo cáo hiển thị trên Terminal."""
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print("=" * 60)
    print("🚀 BÁO CÁO BENCHMARK VLLM")
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

    # Throughput
    throughput_req = len(successful) / total_time
    total_in_tokens = sum(r.input_tokens for r in successful)
    total_out_tokens = sum(r.output_tokens for r in successful)
    throughput_out_tok = total_out_tokens / total_time
    throughput_total_tok = (total_in_tokens + total_out_tokens) / total_time

    single_req_tps_list = [r.single_req_tps for r in successful if r.single_req_tps is not None]
    avg_single_req_tps = statistics.mean(single_req_tps_list) if single_req_tps_list else 0.0

    print(f"📊 THÔNG LƯỢNG (THROUGHPUT):")
    print(f"  [1] TRẢI NGHIỆM TỪNG USER (Single User Speed):")
    print(f"      • Tốc độ sinh chữ       : {avg_single_req_tps:.2f} tokens/s / 1 user")
    print(f"  [2] SỨC MẠNH TOÀN HỆ THỐNG (System Throughput - Concurrency={concurrency}):")
    print(f"      • Tốc độ xử lý Request  : {throughput_req:.2f} req/s")
    print(f"      • Thông lượng Output    : {throughput_out_tok:.2f} tokens/s")
    print(f"      • Thông lượng Tổng      : {throughput_total_tok:.2f} tokens/s")
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
    ttfts = [r.ttft for r in successful if r.ttft is not None]
    tpots = [r.tpot for r in successful if r.tpot is not None]

    print(f"⏱️  ĐỘ TRỄ (LATENCY):")
    print(f"  1. Thời gian tạo token đầu tiên (TTFT - Thời gian phản hồi):")
    print(f"     {format_stats(ttfts)}")
    print(f"  2. Thời gian sinh mỗi token (TPOT - Tốc độ sinh):")
    print(f"     {format_stats(tpots)}")
    print(f"  3. Tổng thời gian hoàn thành Request (Từ đầu đến cuối):")
    print(f"     {format_stats(latencies, 's', 1.0)}")

    print("=" * 60)
    print("💡 Giải thích nhanh thuật ngữ (Dùng cho Blog):")
    print("- TTFT (Time To First Token): Đo lường sự nhạy bén của Server. Phản hồi chữ đầu tiên mất bao lâu.")
    print("- TPOT (Time Per Output Token): Đo tốc độ 'nhả' từng chữ của mô hình sau khi đã bắt đầu sinh.")
    print("- Total Tokens/s: Tổng thông lượng đo lường hiệu năng của toàn bộ phần cứng/server hiện tại.")
    print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="Khung Benchmark chuẩn dành cho vLLM Server")
    parser.add_argument("--url", type=str, default="http://localhost:8000", help="Base URL của vLLM server (ví dụ: http://localhost:8000)")
    parser.add_argument("--model", type=str, default=None, help="Tên model (nếu bỏ trống script sẽ tự tìm từ server)")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Số lượng requests gửi đồng thời")
    parser.add_argument("-n", "--num-requests", type=int, default=30, help="Tổng số requests muốn benchmark")
    args = parser.parse_args()

    # Nhóm các câu hỏi mẫu với độ dài khác nhau để mô phỏng thực tế
    sample_prompts = [
        "Hãy viết một bài văn ngắn khoảng 100 từ về trí tuệ nhân tạo.",
        "Tiếng Việt có bao nhiêu chữ cái? Hãy phân tích các dấu thanh.",
        "Giải thích cơ chế hoạt động của Transformers (LLM) một cách đơn giản cho người không chuyên.",
        "Xin chào, bạn có thể giúp gì cho tôi?",
        "Viết đoạn code Python để thực hiện kiểm tra số nguyên tố và giải thích.",
    ]

    # Chuẩn bị prompts
    test_prompts = [sample_prompts[i % len(sample_prompts)] for i in range(args.num_requests)]

    print(f"🚀 Bắt đầu quá trình Benchmark...")
    print(f"🔗 URL         : {args.url}")
    print(f"⚙️  Tổng request: {args.num_requests}")
    print(f"👥 Đồng thời   : {args.concurrency}\n")

    timeout = httpx.Timeout(300.0) # Thời gian chờ rất lớn để không lỗi lúc chạy tải lớn
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Lấy tên model tự động nếu người dùng không điền
        model_name = args.model
        if not model_name:
            model_name = await fetch_model_name(client, args.url)
        print(f"🧠 Sử dụng Model: {model_name}\n")

        semaphore = asyncio.Semaphore(args.concurrency)
        pbar = ProgressBar(args.num_requests)

        # Tạo tasks
        tasks = [make_request(client, args.url, model_name, prompt, semaphore, pbar) for prompt in test_prompts]

        # Bắt đầu đo tổng thời gian
        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end_time = time.perf_counter()

    # In báo cáo kết quả
    print_metrics(results, end_time - start_time, args.concurrency)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Đã huỷ benchmark bởi người dùng.")
