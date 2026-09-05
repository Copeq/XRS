export type JsonValue =
  | Record<string, unknown>
  | unknown[]
  | string
  | number
  | boolean
  | null;

/** 页面会话 API 请求：自动带 X-XRS-Page:1，JSON 语义返回。 */
export async function pageFetch(path: string, init?: RequestInit): Promise<JsonValue> {
  const headers = new Headers(init?.headers);
  headers.set("X-XRS-Page", "1");
  if (init?.body) headers.set("Content-Type", "application/json");
  const r = await fetch(path, { ...init, headers, cache: "no-store" });
  const text = await r.text();
  let data: JsonValue = null;
  if (text) {
    try {
      data = JSON.parse(text) as JsonValue;
    } catch (_e) {
      data = text;
    }
  }
  if (!r.ok && typeof data === "object" && data && typeof (data as Record<string, unknown>).error === "string") {
    throw new Error(String((data as Record<string, unknown>).error));
  }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return data;
}

export function postJson(path: string, body: Record<string, unknown>): Promise<JsonValue> {
  return pageFetch(path, { method: "POST", body: JSON.stringify(body) });
}
