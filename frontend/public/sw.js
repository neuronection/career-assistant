/* Career Assistant service worker — browser push channel (plan 36). */

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: "Career Assistant", body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "Career Assistant", {
      body: payload.body || "",
      tag: payload.notification_id || payload.kind || "career",
      data: { link: payload.link || "/" },
      icon: "/icon.svg",
      badge: "/icon-light.svg",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = (event.notification.data && event.notification.data.link) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) {
          client.focus();
          client.postMessage({ type: "navigate", link });
          return client;
        }
      }
      return self.clients.openWindow(link);
    })
  );
});
