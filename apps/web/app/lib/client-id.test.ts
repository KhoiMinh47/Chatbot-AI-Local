import { afterEach, describe, expect, it, vi } from "vitest";

import { createClientId } from "./client-id";

describe("createClientId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses randomUUID when the browser provides it", () => {
    const expected = "123e4567-e89b-42d3-a456-426614174000";
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => expected),
    });

    expect(createClientId()).toBe(expected);
  });

  it("creates a valid UUID v4 on an insecure LAN origin without randomUUID", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (target: Uint8Array) => {
        target.fill(0x11);
        return target;
      },
    });

    expect(createClientId()).toBe("11111111-1111-4111-9111-111111111111");
  });
});
