"use client";
import { useEffect } from "react";

export default function CleanupExtension() {
  useEffect(() => {
    // Xóa các thuộc tính do Chrome Extensions (như IDM) tự chèn vào DOM
    // gầy ra lỗi Hydration Mismatch trong Next.js
    const cleanup = () => {
      const elements = document.querySelectorAll("[bis_skin_checked], [bis_register], [bis_size]");
      elements.forEach((el) => {
        el.removeAttribute("bis_skin_checked");
        el.removeAttribute("bis_register");
        el.removeAttribute("bis_size");
      });
    };

    // Chạy khi khởi tạo và quan sát bộ thay đổi của DOM
    cleanup();
    
    // Một MutationObserver để xóa định kỳ nếu Extension cứ cố đấm ăn xôi tiêm vào
    const observer = new MutationObserver((mutations) => {
      let shouldCleanup = false;
      for (const m of mutations) {
        if (m.type === "attributes" && m.attributeName && m.attributeName.startsWith("bis_")) {
          shouldCleanup = true;
          break;
        }
      }
      if (shouldCleanup) cleanup();
    });

    observer.observe(document.body, { attributes: true, subtree: true });

    return () => observer.disconnect();
  }, []);

  return null;
}
