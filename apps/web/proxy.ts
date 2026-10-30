// Optimistic routing only: send obviously signed-out visitors to /login and signed-in users away
// from auth pages. Real authorization happens in FastAPI on every API request.
import { NextResponse, type NextRequest } from "next/server";

const APP_PREFIXES = ["/dashboard", "/research", "/history", "/library", "/templates", "/settings", "/admin"];
const AUTH_PAGES = ["/login", "/register"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = request.cookies.has("dr_session") || request.cookies.has("dr_access");
  if (APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/")) && !signedIn) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", pathname + search);
    return NextResponse.redirect(url);
  }
  const sp = request.nextUrl.searchParams;
  if (AUTH_PAGES.includes(pathname) && signedIn && !sp.get("error") && !sp.get("expired")) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.svg|.*\\.(?:png|svg|jpg|webp|ico|txt)$).*)"],
};
