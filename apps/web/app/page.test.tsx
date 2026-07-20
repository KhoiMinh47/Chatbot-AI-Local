import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "./page";

describe("HomePage", () => {
  it("renders the product introduction and login navigation", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: /hỏi dữ liệu nội bộ/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /nguyên tắc nền tảng/i }),
    ).toBeInTheDocument();

    const loginLinks = screen.getAllByRole("link", { name: /đăng nhập/i });
    expect(loginLinks).toHaveLength(2);
    for (const link of loginLinks) {
      expect(link).toHaveAttribute("href", "/login");
    }
  });
});
