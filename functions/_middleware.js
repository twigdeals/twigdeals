// 301 every non-canonical host (www.twigdeals.com, hockeystickdeals.com, www.hockeystickdeals.com, and the
// production twigdeals.pages.dev) to https://twigdeals.com, keeping path and query.
// Preview hosts (<hash>.twigdeals.pages.dev) and localhost are left alone.
const CANONICAL = "twigdeals.com";
export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  const host = url.hostname.toLowerCase();
  const preview = host.endsWith(".twigdeals.pages.dev");
  if (host !== CANONICAL && !preview && host !== "localhost") {
    return Response.redirect(`https://${CANONICAL}${url.pathname}${url.search}`, 301);
  }
  return next();
}
