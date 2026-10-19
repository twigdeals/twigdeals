// 301 every non-canonical host (www.twigdeals.com, hockeystickdeals.com, www.hockeystickdeals.com) to https://twigdeals.com.
// *.pages.dev preview/production hosts are left alone.
const CANONICAL = "twigdeals.com";
export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  const host = url.hostname.toLowerCase();
  if (host !== CANONICAL && !host.endsWith(".pages.dev") && host !== "localhost") {
    return Response.redirect(`https://${CANONICAL}${url.pathname}${url.search}`, 301);
  }
  return next();
}
