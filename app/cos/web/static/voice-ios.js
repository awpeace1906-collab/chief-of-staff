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

  // Register this iPhone for silent pushes once signed in (this script only runs on signed-in pages).
  window.COSNative.registerPush().catch(function (e) {
    if (window.console) console.log("push registration: " + e.message);
  });

  // A mic button in the Talk tab: tap to record, tap again to stop. The words go into the message box,
  // to Ask or Send as usual. Added here, not in app.js, so the web app in a browser is unchanged.
  function addMicButton() {
    var say = document.getElementById("say"), askBtn = document.getElementById("askBtn");
    if (!say || !askBtn || document.getElementById("micBtn")) return;
    var status = document.getElementById("talkStatus");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "micBtn";
    btn.className = "btn";
    btn.setAttribute("aria-label", "Dictate a message");
    btn.textContent = "🎤 Speak";
    var recording = false, working = false;
    function show(text) { if (status) status.textContent = text; }
    btn.addEventListener("click", function () {
      if (working) return;
      if (!recording) {
        working = true;
        window.COSNative.startRecording().then(function () {
          recording = true;
          btn.textContent = "■ Stop";
          btn.classList.add("primary");
          show("Listening… tap Stop when you're done.");
        }, function (e) { show(e.message); }).then(function () { working = false; });
        return;
      }
      working = true;
      recording = false;
      btn.textContent = "🎤 Speak";
      btn.classList.remove("primary");
      btn.disabled = true;
      show("Transcribing…");
      window.COSNative.stopRecording().then(function (text) {
        if (!text) { show("Didn't catch that. Try again."); return; }
        say.value = say.value.trim() ? say.value.trim() + " " + text : text;
        say.dispatchEvent(new Event("input", { bubbles: true }));
        say.focus();
        show("");
      }, function (e) { show(e.message); }).then(function () { working = false; btn.disabled = false; });
    });
    askBtn.parentNode.insertBefore(btn, askBtn);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addMicButton);
  else addMicButton();
})();
