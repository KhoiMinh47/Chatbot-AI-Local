import Link from "next/link";

const capabilities = [
  {
    number: "01",
    title: "Dữ liệu ở lại cục bộ",
    description:
      "Kiến trúc được thiết kế để tài liệu và quá trình suy luận nằm trong hạ tầng do đội ngũ kiểm soát.",
  },
  {
    number: "02",
    title: "Câu trả lời có căn cứ",
    description:
      "Luồng RAG hướng đến câu trả lời đi kèm nguồn, thay vì biến suy đoán thành thông tin chắc chắn.",
  },
  {
    number: "03",
    title: "Tối ưu cho NVIDIA",
    description:
      "Lớp suy luận sử dụng NVIDIA NIM và được đo lường trên chính phần cứng triển khai.",
  },
] as const;

function BrandMark() {
  return (
    <span
      aria-hidden="true"
      className="grid size-9 place-items-center rounded-lg border border-emerald-300/40 bg-emerald-300/10 text-sm font-black text-emerald-200"
    >
      N
    </span>
  );
}

export default function HomePage() {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 sm:px-8 lg:px-12">
      <header className="flex items-center justify-between border-b border-white/10 py-5">
        <Link
          className="inline-flex items-center gap-3 rounded-md font-semibold tracking-tight text-white"
          href="/"
        >
          <BrandMark />
          <span>NTC Local Knowledge</span>
        </Link>

        <nav aria-label="Điều hướng chính">
          <Link
            className="inline-flex min-h-11 items-center justify-center rounded-full border border-emerald-200/45 px-5 text-sm font-semibold text-emerald-100 transition hover:border-emerald-200 hover:bg-emerald-200/10"
            href="/login"
          >
            Đăng nhập
          </Link>
        </nav>
      </header>

      <main className="flex-1" id="main-content">
        <section className="grid gap-14 py-20 sm:py-28 lg:grid-cols-[1.2fr_0.8fr] lg:items-end lg:py-36">
          <div>
            <p className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-300/25 bg-emerald-300/10 px-3 py-1.5 text-xs font-bold tracking-[0.16em] text-emerald-100 uppercase">
              <span
                className="size-2 rounded-full bg-emerald-300"
                aria-hidden="true"
              />
              Private AI workspace
            </p>
            <h1 className="max-w-4xl text-5xl leading-[0.98] font-semibold tracking-[-0.055em] text-balance sm:text-7xl lg:text-[5.4rem]">
              Hỏi dữ liệu nội bộ.
              <span className="block text-emerald-200">
                Giữ tri thức ở gần.
              </span>
            </h1>
          </div>

          <div className="max-w-xl lg:justify-self-end">
            <p className="text-lg leading-8 text-slate-300">
              Một không gian hỏi đáp được xây dựng cho tài liệu của tổ chức, với
              suy luận cục bộ, nguồn tham chiếu rõ ràng và quyền truy cập có
              kiểm soát.
            </p>
            <Link
              className="mt-8 inline-flex min-h-12 items-center justify-center rounded-full bg-emerald-200 px-6 font-bold text-emerald-950 transition hover:bg-emerald-100"
              href="/login"
            >
              Đi đến đăng nhập
              <span className="ml-2" aria-hidden="true">
                →
              </span>
            </Link>
          </div>
        </section>

        <section
          aria-labelledby="capabilities-title"
          className="pb-20 sm:pb-28"
        >
          <div className="mb-8 flex items-end justify-between gap-6 border-b border-white/10 pb-5">
            <h2
              className="text-sm font-bold tracking-[0.18em] text-slate-300 uppercase"
              id="capabilities-title"
            >
              Nguyên tắc nền tảng
            </h2>
            <p className="hidden text-sm text-slate-400 sm:block">
              Phase 1 · UI skeleton
            </p>
          </div>

          <ul className="grid gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10 md:grid-cols-3">
            {capabilities.map((capability) => (
              <li className="bg-[#0b1513] p-7 sm:p-8" key={capability.number}>
                <p className="mb-16 font-mono text-xs text-emerald-200/80">
                  {capability.number}
                </p>
                <h3 className="text-xl font-semibold tracking-tight text-white">
                  {capability.title}
                </h3>
                <p className="mt-3 leading-7 text-slate-400">
                  {capability.description}
                </p>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="flex flex-col gap-2 border-t border-white/10 py-7 text-sm text-slate-400 sm:flex-row sm:items-center sm:justify-between">
        <p>NTC Local Knowledge</p>
        <p>Hệ thống hỏi đáp tài liệu nội bộ an toàn cục bộ.</p>
      </footer>
    </div>
  );
}
