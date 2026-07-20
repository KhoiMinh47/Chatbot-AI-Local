import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, type Mock } from "vitest";

import LoginPage from "./page";
import { useAuth } from "../lib/auth-context";
import { useRouter } from "next/navigation";
import { ApiError } from "../lib/types";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
}));

// Mock useAuth hook
vi.mock("../lib/auth-context", () => ({
  useAuth: vi.fn(),
}));

describe("LoginPage", () => {
  it("renders form fields and handles login submission successfully", async () => {
    const mockPush = vi.fn();
    const mockLogin = vi.fn().mockResolvedValue(undefined);

    (useRouter as Mock).mockReturnValue({ push: mockPush });
    (useAuth as Mock).mockReturnValue({ login: mockLogin });

    render(<LoginPage />);

    // Verify visual headers
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập" })).toBeInTheDocument();

    const emailInput = screen.getByLabelText("Email");
    const passwordInput = screen.getByLabelText("Mật khẩu");
    const submitBtn = screen.getByRole("button", { name: "Đăng nhập" });

    // Inputs are active (not disabled anymore in Phase 8)
    expect(emailInput).not.toBeDisabled();
    expect(passwordInput).not.toBeDisabled();
    expect(submitBtn).not.toBeDisabled();

    // Fill form
    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "Secret123" } });

    // Submit form
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("test@example.com", "Secret123");
      expect(mockPush).toHaveBeenCalledWith("/chat");
    });
  });

  it("displays validation and credential errors gracefully", async () => {
    const mockLogin = vi.fn().mockRejectedValue(
      new ApiError(401, { code: "INVALID_CREDENTIALS", message: "Mật khẩu không khớp." })
    );

    (useRouter as Mock).mockReturnValue({ push: vi.fn() });
    (useAuth as Mock).mockReturnValue({ login: mockLogin });

    render(<LoginPage />);

    const emailInput = screen.getByLabelText("Email");
    const passwordInput = screen.getByLabelText("Mật khẩu");
    const submitBtn = screen.getByRole("button", { name: "Đăng nhập" });

    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "wrong-password" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Mật khẩu không khớp.");
    });
  });
});
