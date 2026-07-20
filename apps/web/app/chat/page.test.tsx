import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ChatPage from "./page";

vi.mock("../lib/auth-context", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      tenant_id: "tenant-1",
      email: "minh@example.com",
      display_name: "Minh",
      role: "admin",
      is_verified: true,
    },
  }),
}));

vi.mock("../lib/api", () => ({
  apiCreateConversation: vi.fn(),
  apiGetConversation: vi.fn(),
  apiPatchConversation: vi.fn(),
}));

vi.mock("../components/use-chat", () => ({
  useChat: () => ({
    messages: [],
    isStreaming: false,
    startStreaming: vi.fn(),
    stopStreaming: vi.fn(),
    prepareConversation: vi.fn(),
  }),
}));

vi.mock("../components/sidebar", () => ({
  Sidebar: () => <aside aria-label="Sidebar" />,
}));

vi.mock("../components/message-list", () => ({
  MessageList: () => <div>Messages</div>,
}));

vi.mock("../components/citation-drawer", () => ({
  CitationDrawer: () => null,
}));

vi.mock("../components/chat-composer", () => ({
  ChatComposer: ({
    mode,
    onModeChange,
  }: {
    mode: "fast" | "reasoning";
    onModeChange: (mode: "fast" | "reasoning") => void;
  }) => (
    <button type="button" onClick={() => onModeChange("reasoning")}>
      Composer mode: {mode}
    </button>
  ),
}));

describe("ChatPage landing UI", () => {
  it("shows the active model, welcome composer and updates mode immediately", () => {
    render(<ChatPage />);

    expect(
      screen.getByRole("heading", { name: /Nemotron Nano 9B V2/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Xin chào Minh!")).toBeInTheDocument();
    expect(screen.getByText("Hãy bắt đầu nhập câu hỏi của bạn")).toBeInTheDocument();
    expect(screen.getByTestId("active-mode-label")).toHaveTextContent("Fast Mode");

    fireEvent.click(screen.getByRole("button", { name: "Composer mode: fast" }));

    expect(screen.getByTestId("active-mode-label")).toHaveTextContent(
      "Reasoning Mode",
    );
    expect(
      screen.getByRole("button", { name: "Composer mode: reasoning" }),
    ).toBeInTheDocument();
  });
});

