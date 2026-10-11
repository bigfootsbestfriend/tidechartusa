// tidechartusa.com was renamed to Shorebite: send every old address to the same page on shorebite.com (permanent).
export default {
  fetch(req) {
    const u = new URL(req.url);
    return Response.redirect(`https://shorebite.com${u.pathname}${u.search}`, 301);
  },
};
