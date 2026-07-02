import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, getErrorMessage } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("throws ApiError with parsed backend body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve({ path: "Folder is empty" }),
      }),
    );

    await expect(api.stats()).rejects.toBeInstanceOf(ApiError);

    try {
      await api.stats();
    } catch (error) {
      expect(getErrorMessage(error)).toBe("path: Folder is empty");
    }
  });
});
