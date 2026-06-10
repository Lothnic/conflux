import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_URL =
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");

type RouteContext = {
  params: Promise<{
    path?: string[];
  }>;
};

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function createBackendUrl(path: string[], search: string): string {
  const base = BACKEND_URL.replace(/\/+$/, "");
  const pathname = path.map(encodeURIComponent).join("/");
  return `${base}/${pathname}${search}`;
}

function proxyHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  if (!BACKEND_URL) {
    return Response.json(
      { error: "Missing API_URL or NEXT_PUBLIC_API_URL for backend proxy." },
      { status: 500 }
    );
  }

  const { path = [] } = await context.params;
  const upstream = await fetch(createBackendUrl(path, request.nextUrl.search), {
    method: request.method,
    headers: proxyHeaders(request),
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    cache: "no-store",
    duplex: "half",
  } as RequestInit & { duplex: "half" });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream),
  });
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function OPTIONS(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}
