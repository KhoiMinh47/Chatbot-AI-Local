import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageList, formatWorkedDuration } from "./message-list";

describe("message work progress", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats elapsed time using compact worked units", () => {
    expect(formatWorkedDuration(0)).toBe("0s");
    expect(formatWorkedDuration(45_900)).toBe("45s");
    expect(formatWorkedDuration(330_000)).toBe("5m 30s");
    expect(formatWorkedDuration(3_723_000)).toBe("1h 2m 3s");
  });

  it("shows the current SSE phase and running duration", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-20T08:05:30Z"));

    render(
      <MessageList
        messages={[
          {
            id: "assistant-running",
            role: "assistant",
            content: "",
            isStreaming: true,
            progressLabel: "Đang tìm kiếm trong tài liệu...",
            startedAtMs: new Date("2026-07-20T08:00:00Z").getTime(),
          },
        ]}
        isStreaming
        onStop={() => undefined}
        onCitationClick={() => undefined}
      />,
    );

    expect(
      screen.getByText("Đang tìm kiếm trong tài liệu... · 5m 30s"),
    ).toBeInTheDocument();
  });

  it("shows a fallback progress timer when an older message has no start metadata", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-20T08:05:30Z"));

    render(
      <MessageList
        messages={[
          {
            id: "assistant-without-timing-metadata",
            role: "assistant",
            content: "",
            isStreaming: true,
          },
        ]}
        isStreaming
        onStop={() => undefined}
        onCitationClick={() => undefined}
      />,
    );

    expect(screen.getByText("Đang xử lý... · 0s")).toBeInTheDocument();
  });

  it("keeps the final worked duration after completion", () => {
    render(
      <MessageList
        messages={[
          {
            id: "assistant-complete",
            role: "assistant",
            content: "Câu trả lời hoàn chỉnh.",
            isStreaming: false,
            startedAtMs: 1_000,
            completedAtMs: 331_000,
          },
        ]}
        isStreaming={false}
        onStop={() => undefined}
        onCitationClick={() => undefined}
      />,
    );

    expect(screen.getByText("Worked 5m 30s")).toBeInTheDocument();
  });
});
