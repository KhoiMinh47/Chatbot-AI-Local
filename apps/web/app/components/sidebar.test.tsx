import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "./sidebar";

vi.mock("../lib/auth-context", () => ({
  useAuth: () => ({
    logout: vi.fn(),
    user: {
      email: "minh@example.com",
      display_name: "Minh",
    },
  }),
}));

vi.mock("../lib/api", () => ({
  apiCreateConversation: vi.fn(),
  apiDeleteConversation: vi.fn(),
  apiListConversations: vi.fn().mockResolvedValue([
    {
      id: "conversation-1",
      title: "Hội thoại cũ",
      mode: "fast",
      tenant_id: "tenant-1",
      user_id: "user-1",
      created_at: "2026-07-20T00:00:00Z",
      updated_at: "2026-07-20T00:00:00Z",
    },
  ]),
  apiPatchConversation: vi.fn(),
  apiListDocuments: vi.fn().mockResolvedValue({ documents: [], total: 0 }),
  apiDeleteDocument: vi.fn(),
  apiUploadDocument: vi.fn(),
  apiWaitForJob: vi.fn(),
}));

describe("Sidebar navigation", () => {
  it("places files below new chat and supports collapsed icon navigation", async () => {
    render(<Sidebar activeId={null} onSelect={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Hội thoại cũ")).toBeInTheDocument();
    });

    const newChat = screen.getByRole("button", {
      name: "Tạo cuộc trò chuyện mới",
    });
    const files = screen.getByRole("button", { name: /Thư mục File/i });
    const history = screen.getByRole("button", { name: /Lịch sử chat/i });

    expect(
      newChat.compareDocumentPosition(files) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(files.parentElement).toHaveClass("order-2");
    expect(history.closest("nav")).toHaveClass("order-3");

    fireEvent.click(screen.getByRole("button", { name: "Thu gọn thanh bên" }));
    expect(screen.queryByText("NTC AI Assistant")).not.toBeInTheDocument();
    expect(screen.queryByText("Hội thoại cũ")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Lịch sử chat"));
    expect(screen.getByText("NTC AI Assistant")).toBeInTheDocument();
    expect(screen.getByText("Hội thoại cũ")).toBeInTheDocument();
  });
});
