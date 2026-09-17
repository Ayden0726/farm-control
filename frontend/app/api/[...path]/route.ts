import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 300;

function backendBase() {
  const env = process.env;
  const fromEnv = env["API_INTERNAL_URL"] || env["BACKEND_URL"];
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  if (env.NODE_ENV === "development") return "http://127.0.0.1:8472";
  return "http://backend:8000";
}

const HOP = new Set([
  "connection",
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

async function proxy(req: NextRequest, path: string[]) {
  const dest = `${backendBase()}/api/${path.join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: "manual",
  };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = req.body;
    Object.assign(init, { duplex: "half" });
  }
  try {
    const res = await fetch(dest, init);
    const out = new Headers();
    res.headers.forEach((value, key) => {
      if (!HOP.has(key.toLowerCase())) out.set(key, value);
    });
    return new NextResponse(res.body, { status: res.status, headers: out });
  } catch (err) {
    console.error("API proxy failed", dest, err);
    return NextResponse.json(
      {
        detail:
          "The farm API is not reachable yet. Wait 15 seconds and click Complete setup again. If it keeps failing, run: docker compose logs backend",
      },
      { status: 503 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function PATCH(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function OPTIONS(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
