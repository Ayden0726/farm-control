import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 60;

function backendBase() {
  return (process.env.API_INTERNAL_URL || "http://127.0.0.1:8472").replace(/\/$/, "");
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
      { detail: "Print FarmOS API is starting. Wait a few seconds and retry." },
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
