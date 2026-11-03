import Foundation
import EventKit
import Capacitor

/// EventKit bridge: `Capacitor.Plugins.Calendar` in JS (see app/cos/web/static/voice-ios.js).
@objc(CalendarPlugin)
public class CalendarPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "CalendarPlugin"
    public let jsName = "Calendar"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "requestAccess", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "events", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "createEvent", returnType: CAPPluginReturnPromise),
    ]

    private let store = EKEventStore()

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let isoPlain = ISO8601DateFormatter()

    private func date(_ s: String?) -> Date? {
        guard let s else { return nil }
        return Self.iso.date(from: s) ?? Self.isoPlain.date(from: s)
    }

    /// requestAccess({level: 'full' | 'write'}) -> {granted}
    @objc func requestAccess(_ call: CAPPluginCall) {
        let level = call.getString("level") ?? "full"
        let done: (Bool, Error?) -> Void = { granted, error in
            if let error { call.reject(error.localizedDescription); return }
            call.resolve(["granted": granted])
        }
        if #available(iOS 17.0, *) {
            if level == "write" {
                store.requestWriteOnlyAccessToEvents(completion: done)
            } else {
                store.requestFullAccessToEvents(completion: done)
            }
        } else {
            store.requestAccess(to: .event, completion: done)
        }
    }

    /// events({start, end}) -> {events: [{id, title, start, end, allDay, location, calendar}]}
    @objc func events(_ call: CAPPluginCall) {
        guard let start = date(call.getString("start")), let end = date(call.getString("end")) else {
            call.reject("start and end must be ISO 8601 dates")
            return
        }
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)
        let out: [[String: Any]] = store.events(matching: predicate).map { e in
            [
                "id": e.eventIdentifier ?? "",
                "title": e.title ?? "",
                "start": Self.iso.string(from: e.startDate),
                "end": Self.iso.string(from: e.endDate),
                "allDay": e.isAllDay,
                "location": e.location ?? "",
                "calendar": e.calendar?.title ?? "",
            ]
        }
        call.resolve(["events": out])
    }

    /// createEvent({title, start, end}) -> {id}
    @objc func createEvent(_ call: CAPPluginCall) {
        guard let title = call.getString("title"), !title.isEmpty,
              let start = date(call.getString("start")), let end = date(call.getString("end")) else {
            call.reject("title, start and end (ISO 8601) are required")
            return
        }
        guard let calendar = store.defaultCalendarForNewEvents else {
            call.reject("no default calendar; allow calendar access first")
            return
        }
        let event = EKEvent(eventStore: store)
        event.title = title
        event.startDate = start
        event.endDate = end
        event.calendar = calendar
        do {
            try store.save(event, span: .thisEvent, commit: true)
            call.resolve(["id": event.eventIdentifier ?? ""])
        } catch {
            call.reject(error.localizedDescription)
        }
    }
}
