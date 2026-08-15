/* Web Push bridge between the game (GDScript) and the browser.
 *
 * Godot's JavaScriptBridge.eval() is synchronous and everything here is async,
 * so nothing returns a value to the game directly. Instead every operation
 * updates `HJPush.state`, which the game reads whenever it wants to know where
 * things stand. One shape, polled — much easier to reason about than callbacks
 * marshalled across the bridge.
 *
 * On iOS this only works for a PWA added to the home screen. Safari tabs cannot
 * receive push, and `PushManager` is simply absent there, which `supported`
 * reports honestly rather than failing later.
 */
(function () {
  "use strict";

  var state = {
    supported: false,
    standalone: false,
    permission: "default",   // default | granted | denied
    subscribed: false,
    id: "",
    busy: false,
    error: "",
    lastPush: "",
  };

  function save() {
    try {
      localStorage.setItem("hj_push_id", state.id || "");
    } catch (e) { /* private mode */ }
  }

  function load() {
    try {
      state.id = localStorage.getItem("hj_push_id") || "";
    } catch (e) { /* private mode */ }
  }

  function refresh() {
    state.supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    state.standalone = window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
    state.permission = state.supported ? Notification.permission : "unsupported";
    if (!state.supported) return Promise.resolve(state);
    return navigator.serviceWorker.ready
      .then(function (reg) { return reg.pushManager.getSubscription(); })
      .then(function (sub) {
        state.subscribed = !!sub;
        return state;
      })
      .catch(function () { return state; });
  }

  /* VAPID public keys travel as base64url and subscribe() wants a Uint8Array. */
  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(base64);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
    return out;
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    }).then(function (r) {
      if (!r.ok) throw new Error(path + " -> " + r.status);
      return r.json();
    });
  }

  function tzOffset() {
    // JS reports minutes *behind* UTC; the server wants minutes east of it.
    return -new Date().getTimezoneOffset();
  }

  var HJPush = {
    state: state,

    /* Ask for permission and subscribe. Must be called from a user gesture —
     * browsers refuse a permission prompt that nobody asked for. */
    enable: function (prefsJson) {
      if (state.busy) return;
      state.busy = true;
      state.error = "";
      var prefs = {};
      try { prefs = JSON.parse(prefsJson || "{}"); } catch (e) { prefs = {}; }
      prefs.tz_offset = tzOffset();

      Promise.resolve()
        .then(function () {
          if (!state.supported) throw new Error("push not supported here");
          return Notification.requestPermission();
        })
        .then(function (permission) {
          state.permission = permission;
          if (permission !== "granted") throw new Error("permission " + permission);
          return fetch("push/key", { credentials: "same-origin" }).then(function (r) { return r.json(); });
        })
        .then(function (keyRes) {
          return navigator.serviceWorker.ready.then(function (reg) {
            return reg.pushManager.subscribe({
              userVisibleOnly: true,
              applicationServerKey: urlBase64ToUint8Array(keyRes.publicKey),
            });
          });
        })
        .then(function (sub) {
          return post("push/subscribe", { subscription: sub.toJSON(), prefs: prefs });
        })
        .then(function (res) {
          state.id = res.id;
          state.subscribed = true;
          save();
        })
        .catch(function (err) { state.error = String(err.message || err); })
        .then(function () { state.busy = false; return refresh(); });
    },

    disable: function () {
      if (state.busy) return;
      state.busy = true;
      navigator.serviceWorker.ready
        .then(function (reg) { return reg.pushManager.getSubscription(); })
        .then(function (sub) { return sub ? sub.unsubscribe() : null; })
        .then(function () {
          if (!state.id) return null;
          return fetch("push/subscribe", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ id: state.id }),
          });
        })
        .then(function () {
          state.subscribed = false;
          state.id = "";
          save();
        })
        .catch(function (err) { state.error = String(err.message || err); })
        .then(function () { state.busy = false; });
    },

    /* Replaces the whole schedule server-side. The game recomputes and calls
     * this whenever a deadline moves. */
    schedule: function (remindersJson) {
      if (!state.id) return;
      var reminders = [];
      try { reminders = JSON.parse(remindersJson || "[]"); } catch (e) { return; }
      post("push/schedule", { id: state.id, reminders: reminders })
        .catch(function (err) { state.error = String(err.message || err); });
    },

    prefs: function (prefsJson) {
      if (!state.id) return;
      var prefs = {};
      try { prefs = JSON.parse(prefsJson || "{}"); } catch (e) { return; }
      prefs.tz_offset = tzOffset();
      post("push/prefs", { id: state.id, prefs: prefs })
        .catch(function (err) { state.error = String(err.message || err); });
    },

    test: function () {
      if (!state.id) { state.error = "not subscribed"; return; }
      post("push/test", { id: state.id })
        .catch(function (err) { state.error = String(err.message || err); });
    },

    status: function () { return JSON.stringify(state); },
  };

  navigator.serviceWorker && navigator.serviceWorker.addEventListener("message", function (event) {
    if (event.data && event.data.type === "push") {
      state.lastPush = event.data.title + ": " + event.data.body;
      console.log("[push] delivered —", state.lastPush);
    }
  });

  load();
  window.HJPush = HJPush;
  if (document.readyState === "complete") refresh();
  else window.addEventListener("load", refresh);
})();
