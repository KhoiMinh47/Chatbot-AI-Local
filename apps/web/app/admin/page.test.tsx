import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, type Mock } from "vitest";

import AdminDashboardOverview from "./page";
import AdminLayout from "./layout";
import { useAuth } from "../lib/auth-context";
import { useRouter } from "next/navigation";
import { apiAdminGetStats, apiAdminGetConfig, apiAdminGetServices } from "../lib/api";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
  usePathname: vi.fn().mockReturnValue("/admin"),
}));

// Mock useAuth hook
vi.mock("../lib/auth-context", () => ({
  useAuth: vi.fn(),
}));

// Mock administrative APIs
vi.mock("../lib/api", () => ({
  apiAdminGetStats: vi.fn(),
  apiAdminGetConfig: vi.fn(),
  apiAdminGetServices: vi.fn(),
}));

describe("Admin Layout Guarding", () => {
  it("guards paths and blocks regular non-admin user with a 403 Forbidden alert", () => {
    (useRouter as Mock).mockReturnValue({ replace: vi.fn() });
    (useAuth as Mock).mockReturnValue({
      user: {
        id: "user-id",
        email: "member@congty.vn",
        display_name: "Regular Member",
        role: "user",
      },
      isLoading: false,
      isAuthenticated: true,
    });

    render(
      <AdminLayout>
        <div>Secret Admin Content</div>
      </AdminLayout>
    );

    // Should render Access Denied message instead of children content
    expect(screen.getByText("Truy cập bị từ chối")).toBeInTheDocument();
    expect(screen.getByText(/không có quyền quản trị hệ thống/i)).toBeInTheDocument();
    expect(screen.queryByText("Secret Admin Content")).toBeNull();
  });

  it("permits admin role to render nested child panel elements", () => {
    (useRouter as Mock).mockReturnValue({ replace: vi.fn() });
    (useAuth as Mock).mockReturnValue({
      user: {
        id: "admin-id",
        email: "boss@congty.vn",
        display_name: "Super Admin",
        role: "admin",
      },
      isLoading: false,
      isAuthenticated: true,
    });

    render(
      <AdminLayout>
        <div>Secret Admin Content</div>
      </AdminLayout>
    );

    expect(screen.getByText("Secret Admin Content")).toBeInTheDocument();
    expect(screen.queryByText("Truy cập bị từ chối")).toBeNull();
  });
});

describe("Admin Dashboard Overview Component", () => {
  it("fetches and renders statistical summaries and dependency statuses", async () => {
    // Setup API mocks
    (apiAdminGetStats as Mock).mockResolvedValue({
      users_count: 42,
      documents_count: 108,
    });
    (apiAdminGetConfig as Mock).mockResolvedValue({
      nim_clients_enabled: true,
      llm_model: "nvidia/nemotron-nano-9b-v2",
      llm_model_version: "1.0.0",
      embed_model: "nvidia/llama-nemotron-embed-300m-v2",
      embed_model_version: "1.13.0",
      prompt_version: "phase6-grounded-v4",
      prompt_sha256: "test-hash",
      graph_version: "phase6-stategraph-v2",
    });
    (apiAdminGetServices as Mock).mockResolvedValue({
      ready: true,
      dependencies: [
        { name: "Database", status: "ok", required_for_readiness: true },
        { name: "Redis", status: "ok", required_for_readiness: true },
      ],
    });

    render(<AdminDashboardOverview />);

    // Wait for async fetch loads
    await waitFor(() => {
      expect(screen.getByText("42")).toBeInTheDocument();
      expect(screen.getByText("108")).toBeInTheDocument();
      expect(screen.getByText("Database")).toBeInTheDocument();
      expect(screen.getByText("nvidia/nemotron-nano-9b-v2")).toBeInTheDocument();
      expect(screen.getByText("nvidia/llama-nemotron-embed-300m-v2")).toBeInTheDocument();
    });
  });
});
