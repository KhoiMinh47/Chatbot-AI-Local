import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { AuthProvider } from "./lib/auth-context";

export const metadata: Metadata = {
  title: {
    default: "NTC Local Knowledge",
    template: "%s · NTC Local Knowledge",
  },
  description:
    "Không gian hỏi đáp tài liệu nội bộ vận hành trên hạ tầng NVIDIA cục bộ.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="vi">
      <body>
        <a className="skip-link" href="#main-content">
          Bỏ qua để đến nội dung chính
        </a>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
