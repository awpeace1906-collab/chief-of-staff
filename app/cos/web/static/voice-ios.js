// Native bridge for the iOS shell (ios-shell/). Inert in a browser: it does nothing unless the page
// runs inside Capacitor on a native platform. Exposes window.COSNative; app.js does not use it yet.
(function () {
  "use strict";
  var Cap = window.Capacitor;
  if (!Cap || typeof Cap.isNativePlatform !== "function" || !Cap.isNativePlatform()) return;

  function plugin(name) {
    var p = Cap.Plugins && Cap.Plugins[name];
    if (!p) throw new Error("native plugin " + name + " is not available");
    return p;
  }

  function api(path, opts) {
    return fetch(path, Object.assign({ credentials: "same-origin" }, opts)).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          throw new Error(b.detail || (path + " returned " + r.status));
        });
      }
      return r.json();
    });
  }

  function b64ToBlob(b64, mime) {
    var bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }

  var pushPromise = null;

  window.COSNative = {
    // Calendar (EventKit, on the phone)
    calendarAccess: function (level) { return plugin("Calendar").requestAccess({ level: level || "full" }); },
    calendarEvents: function (startISO, endISO) {
      return plugin("Calendar").events({ start: startISO, end: endISO }).then(function (r) { return r.events || []; });
    },
    createEvent: function (ev) {
      return plugin("Calendar").createEvent({ title: ev.title, start: ev.start, end: ev.end });
    },

    // Voice: record on the phone, transcribe on the server
    startRecording: function () { return plugin("Voice").startRecording(); },
    stopRecording: function () {
      return plugin("Voice").stopRecording().then(function (r) {
        var mime = r.mime || "audio/mp4";
        var form = new FormData();
        form.append("audio", b64ToBlob(r.base64, mime), "voice.m4a");
        return api("/api/voice/transcribe", { method: "POST", body: form });
      }).then(function (b) { return b.text || ""; });
    },

    // Push: ask permission, register with APNs, tell the server the device token
    registerPush: function () {
      if (pushPromise) return pushPromise;
      var Push = plugin("PushNotifications");
      pushPromise = new Promise(function (resolve, reject) {
        Push.addListener("registration", function (t) {
          api("/api/push/register", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: t.value })
          }).then(function () { resolve(t.value); }, reject);
        });
        Push.addListener("registrationError", function (e) { reject(new Error((e && e.error) || "push registration failed")); });
        Push.requestPermissions().then(function (p) {
          if (p.receive !== "granted") throw new Error("notifications were not allowed");
          return Push.register();
        }).catch(reject);
      });
      pushPromise.catch(function () { pushPromise = null; });
      return pushPromise;
    }
  };
})();
