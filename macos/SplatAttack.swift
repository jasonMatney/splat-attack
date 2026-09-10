import SwiftUI
import UniformTypeIdentifiers
import AppKit

let accent = Color(red: 1, green: 0.43, blue: 0.22)
let repo = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "SplatRepository") as? String ?? FileManager.default.currentDirectoryPath)

@MainActor final class Studio: ObservableObject {
    @Published var video: URL?
    @Published var preset = "office"
    @Published var allowPartial = false
    @Published var stage = "ready"
    @Published var message = "Choose a video to begin."
    @Published var running = false
    @Published var output: URL?
    @Published var result: URL?
    @Published var registered = ""
    @Published var warning = ""
    @Published var ready = false
    @Published var recent: [URL] = []
    var process: Process?
    var timer: Timer?
    var console: FileHandle?

    init() {
        let fm = FileManager.default
        ready = fm.isExecutableFile(atPath: repo.appendingPathComponent(".venv/bin/python").path)
            && fm.isExecutableFile(atPath: repo.appendingPathComponent(".tools/brush/brush_app").path)
        if !ready { message = "Run scripts/setup-mac.sh in the repository to install the reconstruction tools." }
        refreshRecent()
    }
    func refreshRecent() {
        recent = ((try? FileManager.default.contentsOfDirectory(at: repo.appendingPathComponent("runs"), includingPropertiesForKeys: [.creationDateKey])) ?? [])
            .filter { FileManager.default.fileExists(atPath: $0.appendingPathComponent("status.json").path) }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
    }
    func chooseVideo() {
        let panel = NSOpenPanel()
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.allowedContentTypes = [.movie, .video]; panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url { select(url) }
    }
    func select(_ url: URL) {
        guard !running else { return }
        video = url; stage = "ready"; message = "Ready to reconstruct on this Mac."
        result = nil; output = nil; registered = ""; warning = ""
    }
    func start() {
        guard let video, !running else { return }
        let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        let folder = repo.appendingPathComponent("runs/\(stamp)-\(UUID().uuidString.prefix(6))")
        output = folder; result = nil; registered = ""; warning = ""; stage = "prepare"
        message = "Checking your video and local tools…"
        let p = Process()
        p.executableURL = repo.appendingPathComponent(".venv/bin/python")
        p.currentDirectoryURL = repo
        p.arguments = ["-u", "-m", "splat_attack.pipeline", "run", video.path, "--output", folder.path, "--preset", preset]
        if allowPartial { p.arguments?.append("--allow-partial") }
        var env = ProcessInfo.processInfo.environment
        env["SPLAT_PROCESS_GROUP"] = "1"
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        p.environment = env
        // Keep console output outside the not-yet-created job directory until startup.
        let log = repo.appendingPathComponent("runs/\(folder.lastPathComponent).console.log")
        do {
            try FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
            FileManager.default.createFile(atPath: log.path, contents: nil)
            console = try FileHandle(forWritingTo: log)
            p.standardOutput = console; p.standardError = console
            p.terminationHandler = { [weak self] proc in
                Task { @MainActor in
                    guard let self else { return }
                    self.poll()
                    self.running = false
                    self.timer?.invalidate(); self.timer = nil
                    try? self.console?.close(); self.console = nil
                    if FileManager.default.fileExists(atPath: folder.path) {
                        try? FileManager.default.moveItem(at: log, to: folder.appendingPathComponent("console.log"))
                    }
                    if self.stage != "complete" && self.stage != "failed" && self.stage != "cancelled" {
                        self.stage = "failed"
                        self.message = "Reconstruction stopped (exit \(proc.terminationStatus)). Open the job folder to inspect its log."
                    }
                    self.process = nil; self.refreshRecent()
                }
            }
            try p.run(); process = p; running = true
            timer = Timer.scheduledTimer(withTimeInterval: 0.6, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.poll() }
            }
        } catch { stage = "failed"; message = error.localizedDescription; running = false }
    }
    func poll() {
        guard let output, let data = try? Data(contentsOf: output.appendingPathComponent("status.json")),
              let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        stage = state["stage"] as? String ?? stage
        message = state["message"] as? String ?? message
        if let path = state["result"] as? String { result = URL(fileURLWithPath: path) }
        if let n = state["registered"] as? Int, let all = state["frames"] as? Int { registered = "\(n) / \(all) camera views connected" }
        warning = (state["warnings"] as? [String] ?? []).joined(separator: " ")
    }
    func restore(_ folder: URL) {
        guard !running else { return }
        output = folder; result = nil; registered = ""; warning = ""; poll()
        if !["complete", "failed", "cancelled"].contains(stage) {
            message += " This saved job has not recorded a final result. Check its logs for progress."
        }
    }
    func stop() {
        guard let p = process, p.isRunning else { return }
        stage = "cancelled"; message = "Stopping reconstruction…"
        let pid = p.processIdentifier
        if getpgid(pid) == pid { kill(-pid, SIGTERM) } else { p.terminate() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            if self?.process === p, p.isRunning {
                if getpgid(pid) == pid { kill(-pid, SIGKILL) } else { kill(pid, SIGKILL) }
            }
        }
    }
    func openResult() {
        guard let result else { return }
        let config = NSWorkspace.OpenConfiguration()
        config.arguments = [result.path, "--with-viewer"]
        config.createsNewApplicationInstance = true
        NSWorkspace.shared.openApplication(at: repo.appendingPathComponent("dist/Brush Viewer.app"), configuration: config) { _, error in
            if let error { Task { @MainActor in self.message = error.localizedDescription } }
        }
    }
    func reveal() {
        guard let output else { return }
        NSWorkspace.shared.open(output.deletingLastPathComponent().appendingPathComponent(FileManager.default.fileExists(atPath: output.path) ? output.lastPathComponent : ""))
    }
}

struct ContentView: View {
    @StateObject var studio = Studio()
    @State private var targeted = false
    let steps = [("extract", "Extract frames"), ("features", "Find features"), ("match", "Match views"), ("cameras", "Solve cameras"), ("undistort", "Prepare scene"), ("train", "Train splat")]
    var body: some View {
        ScrollView {
        VStack(alignment: .leading, spacing: 24) {
            HStack(alignment: .firstTextBaseline) {
                Text("SPLAT / ATTACK").font(.system(size: 25, weight: .black, design: .monospaced))
                Spacer()
                Label("LOCAL WORKSPACE", systemImage: "desktopcomputer").font(.system(size: 12, weight: .medium, design: .monospaced)).foregroundStyle(.secondary)
            }
            HStack(alignment: .top, spacing: 30) {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Your office. In 3D.").font(.system(size: 32, weight: .semibold))
                    Text("AirDrop an iPhone video to this Mac, then build a splat from your footage.").font(.system(size: 16)).foregroundStyle(.secondary)
                    Button { studio.chooseVideo() } label: {
                        VStack(spacing: 14) {
                            Image(systemName: studio.video == nil ? "video.badge.plus" : "film.stack").font(.system(size: 34)).foregroundStyle(accent)
                            Text(studio.video?.lastPathComponent ?? "Drop your video here").font(.system(size: 17, weight: .medium)).lineLimit(2)
                            Text(studio.video == nil ? "or choose a MOV / MP4 file" : "Choose a different video").font(.system(size: 14)).foregroundStyle(.secondary)
                        }.frame(maxWidth: .infinity).frame(height: 170)
                            .background(targeted ? accent.opacity(0.14) : Color.white.opacity(0.035))
                            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(targeted ? accent : Color.white.opacity(0.2), style: StrokeStyle(lineWidth: 1, dash: [6])))
                    }.buttonStyle(.plain).disabled(studio.running)
                    .onDrop(of: [UTType.fileURL], isTargeted: $targeted) { providers in
                        guard !studio.running, let first = providers.first else { return false }
                        _ = first.loadObject(ofClass: URL.self) { url, _ in
                            if let url { Task { @MainActor in studio.select(url) } }
                        }
                        return true
                    }
                    VStack(alignment: .leading, spacing: 9) {
                        Text("Reconstruction quality").font(.system(size: 14, weight: .medium))
                        Picker("Quality", selection: $studio.preset) {
                            Text("Quick preview").tag("preview")
                            Text("Office").tag("office")
                            Text("High detail").tag("detail")
                        }.pickerStyle(.segmented).labelsHidden().disabled(studio.running)
                        Text(studio.preset == "preview" ? "6,000 steps · up to 360 frames · check your capture first" : studio.preset == "office" ? "20,000 steps · up to 900 frames · balanced quality" : "30,000 steps · up to 1,500 frames · uses more memory")
                            .font(.system(size: 13)).foregroundStyle(.secondary)
                        if ProcessInfo.processInfo.physicalMemory <= 8 * 1024 * 1024 * 1024 {
                            Text("8 GB Mac: training automatically uses a smaller scene budget to reduce memory use.")
                                .font(.system(size: 13)).foregroundStyle(accent).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    HStack {
                        Button(studio.running ? "Reconstructing…" : "Generate interior splat") { studio.start() }
                            .buttonStyle(.borderedProminent).tint(accent).controlSize(.large)
                            .disabled(studio.video == nil || studio.running || !studio.ready)
                        if studio.running { Button("Stop") { studio.stop() }.controlSize(.large) }
                    }
                    Toggle("Keep a partial scene if coverage is incomplete", isOn: $studio.allowPartial)
                        .font(.system(size: 13)).disabled(studio.running)
                    Text("Your video and scene stay on this Mac. Training uses your GPU; keep the Mac plugged in and awake.").font(.system(size: 13)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .leading, spacing: 17) {
                    Text("RECONSTRUCTION").font(.system(size: 12, weight: .semibold, design: .monospaced)).foregroundStyle(.secondary)
                    ForEach(Array(steps.enumerated()), id: \.offset) { index, item in
                        HStack(spacing: 12) {
                            Text(String(format: "%02d", index + 1)).font(.system(size: 13, design: .monospaced))
                                .foregroundStyle(studio.stage == item.0 ? accent : .secondary)
                            Text(item.1).font(.system(size: 15, weight: studio.stage == item.0 ? .semibold : .regular))
                            Spacer()
                            if studio.stage == item.0 && studio.running { ProgressView().controlSize(.small) }
                            if studio.stage == "complete" { Image(systemName: "checkmark").foregroundStyle(accent) }
                        }
                    }
                    Divider()
                    Text(studio.message).font(.system(size: 14)).foregroundStyle(studio.stage == "failed" ? Color.orange : Color.primary).fixedSize(horizontal: false, vertical: true)
                    if !studio.registered.isEmpty { Text(studio.registered).font(.system(size: 13, design: .monospaced)).foregroundStyle(accent) }
                    if !studio.warning.isEmpty { Text(studio.warning).font(.system(size: 13)).foregroundStyle(.orange) }
                    if studio.result != nil {
                        Button("Open splat in Brush", systemImage: "cube.transparent") { studio.openResult() }.buttonStyle(.borderedProminent).tint(accent)
                    }
                    if studio.output != nil { Button("Show files & logs", systemImage: "folder") { studio.reveal() } }
                }.padding(22).frame(width: 270, alignment: .leading).background(Color.white.opacity(0.045)).clipShape(RoundedRectangle(cornerRadius: 12))
            }
            Divider()
            HStack(alignment: .top, spacing: 28) {
                VStack(alignment: .leading, spacing: 7) {
                    Text("A better capture makes a better splat").font(.system(size: 15, weight: .semibold))
                    Text("Use the 1× lens at 4K / 30 fps. Walk slowly around the room for 1–3 minutes, keeping furniture in view. Revisit your starting point. Keep the lens fixed; avoid standing still and panning.").font(.system(size: 14)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                VStack(alignment: .leading, spacing: 7) {
                    Text("Keep the room still").font(.system(size: 15, weight: .semibold))
                    Text("Turn lights on. Avoid people moving, mirrors and blank walls. Lock focus/exposure when practical. Standard video works best; avoid Cinematic and Action modes.").font(.system(size: 14)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if !studio.recent.isEmpty {
                Menu("Recent reconstructions") {
                    ForEach(studio.recent.prefix(12), id: \.self) { folder in
                        Button(folder.lastPathComponent) { studio.restore(folder) }
                    }
                }.disabled(studio.running).frame(width: 245)
            }
        }.padding(30).frame(maxWidth: .infinity, alignment: .leading)
        }.frame(minWidth: 890, minHeight: 720).background(Color(red: 0.065, green: 0.073, blue: 0.082))
            .preferredColorScheme(.dark)
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in studio.stop() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in studio.refreshRecent() }
    }
}

@main struct SplatAttackApp: App {
    var body: some Scene {
        WindowGroup("Splat Attack") { ContentView() }
            .windowStyle(.hiddenTitleBar)
            .defaultSize(width: 960, height: 790)
    }
}
