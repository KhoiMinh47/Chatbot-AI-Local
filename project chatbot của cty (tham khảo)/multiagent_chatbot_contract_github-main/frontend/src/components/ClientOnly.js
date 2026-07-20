"use client";
/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useState } from "react";

export default function ClientOnly({ children }) {
  const [hasMounted, setHasMounted] = useState(false);

  useEffect(() => {
    setHasMounted(true);
  }, []);

  if (!hasMounted) {
    return null;
  }

  return <>{children}</>;
}
