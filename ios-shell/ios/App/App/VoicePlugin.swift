import Foundation
import AVFoundation
import Capacitor

/// Microphone recorder: `Capacitor.Plugins.Voice` in JS. Records AAC, 16 kHz mono, to a temp .m4a;
/// the web app sends it to /api/voice/transcribe.
@objc(VoicePlugin)
public class VoicePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "VoicePlugin"
    public let jsName = "Voice"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "startRecording", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopRecording", returnType: CAPPluginReturnPromise),
    ]

    private var recorder: AVAudioRecorder?
    private var fileURL: URL?

    @objc func startRecording(_ call: CAPPluginCall) {
        let begin: (Bool) -> Void = { granted in
            DispatchQueue.main.async {
                guard granted else { call.reject("microphone access was not allowed"); return }
                self.begin(call)
            }
        }
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission(completionHandler: begin)
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission(begin)
        }
    }

    private func begin(_ call: CAPPluginCall) {
        recorder?.stop()
        cleanup()
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("cos-voice-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .default)
            try session.setActive(true)
            let r = try AVAudioRecorder(url: url, settings: settings)
            guard r.record() else { call.reject("could not start recording"); return }
            recorder = r
            fileURL = url
            call.resolve()
        } catch {
            call.reject(error.localizedDescription)
        }
    }

    /// stopRecording() -> {base64, mime: "audio/mp4"}; the temp file is deleted.
    @objc func stopRecording(_ call: CAPPluginCall) {
        guard let r = recorder, let url = fileURL else { call.reject("not recording"); return }
        r.stop()
        recorder = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        defer { cleanup() }
        do {
            let data = try Data(contentsOf: url)
            call.resolve(["base64": data.base64EncodedString(), "mime": "audio/mp4"])
        } catch {
            call.reject(error.localizedDescription)
        }
    }

    private func cleanup() {
        if let url = fileURL { try? FileManager.default.removeItem(at: url) }
        fileURL = nil
    }
}
