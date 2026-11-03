import Capacitor

/// Capacitor 6 doesn't auto-register plugins compiled into the app target, so register them here.
/// Main.storyboard's Bridge View Controller uses this class (Custom Class: MainViewController, Module: App).
class MainViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(CalendarPlugin())
        bridge?.registerPluginInstance(VoicePlugin())
    }
}
