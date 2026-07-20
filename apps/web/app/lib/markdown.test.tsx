import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "./markdown";

describe("Markdown Component", () => {
  it("renders simple text paragraphs", () => {
    render(<Markdown content="Hello World" />);
    expect(screen.getByText("Hello World")).toBeInTheDocument();
  });

  it("renders bold and italic text styles", () => {
    render(<Markdown content="This is **bold** and *italic* text." />);
    expect(screen.getByText(/This is/i)).toBeInTheDocument();
    expect(screen.getByText("bold")).toHaveClass("font-bold");
    expect(screen.getByText("italic")).toHaveClass("italic");
  });

  it("renders inline code formatting", () => {
    render(<Markdown content="Use `const a = 1` for inline code." />);
    expect(screen.getByText("const a = 1")).toHaveClass("font-mono");
  });

  it("renders bulleted list blocks", () => {
    render(
      <Markdown
        content={`- First item
- Second item`}
      />,
    );
    expect(screen.getByText("First item")).toBeInTheDocument();
    expect(screen.getByText("Second item")).toBeInTheDocument();
  });

  it("renders citation tokens as interactive buttons and handles click", () => {
    const mockClick = vi.fn();
    const citationId = "C0123456789abcdef0123456789abcdef";
    render(
      <Markdown
        content={`Bằng chứng từ tài liệu [CITE:${citationId}].`}
        onCitationClick={mockClick}
      />,
    );

    const citationBtn = screen.getByRole("button", {
      name: `Xem nguồn trích dẫn ${citationId}`,
    });
    expect(citationBtn).toBeInTheDocument();
    expect(citationBtn).toHaveTextContent("Nguồn");

    fireEvent.click(citationBtn);
    expect(mockClick).toHaveBeenCalledWith(citationId);
  });

  it("prevents script execution (XSS safe rendering by React elements mapping)", () => {
    const rawContent =
      "Đây là mã độc <script>alert('XSS')</script> & <img src=x onerror=alert(1)>";
    render(<Markdown content={rawContent} />);

    // Since our custom parser renders parts as plain text strings (excluding matches),
    // raw tags are treated as plain text strings rather than dangerously parsed HTML.
    expect(screen.queryByText("alert('XSS')")).toBeNull();
    // React automatically escapes content. Verify the raw characters render as text safe node.
    expect(
      screen.getByText(/đây là mã độc <script>alert\('XSS'\)<\/script>/i),
    ).toBeInTheDocument();
  });
});
