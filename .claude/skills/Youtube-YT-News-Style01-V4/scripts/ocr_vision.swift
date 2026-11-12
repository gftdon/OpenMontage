// macOS Vision OCR for the YT-News V4 frame checks (local only, no network).
//
//   ocr_vision <image> [<image> ...]
//   ocr_vision --list <file-with-one-path-per-line>
//
// Prints one JSON object per input line, in input order:
//   {"path":"...","ok":true,"lines":["text", ...]}
//   {"path":"...","ok":false,"error":"..."}          (unreadable image / Vision error)
// Exit codes: 0 = ran (per-image errors are reported in the JSON), 2 = usage error,
// 3 = Vision framework unusable on this machine.
import Foundation
import Vision
import ImageIO

func emit(_ obj: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: obj, options: [.withoutEscapingSlashes]),
       let s = String(data: data, encoding: .utf8) {
        print(s)
    }
}

var args = Array(CommandLine.arguments.dropFirst())
var paths: [String] = []
if args.first == "--list" {
    guard args.count == 2, let text = try? String(contentsOfFile: args[1], encoding: .utf8) else {
        FileHandle.standardError.write("usage: ocr_vision --list <file>\n".data(using: .utf8)!)
        exit(2)
    }
    paths = text.split(whereSeparator: { $0 == "\n" || $0 == "\r" }).map(String.init).filter { !$0.isEmpty }
} else {
    paths = args
}
if paths.isEmpty {
    FileHandle.standardError.write("usage: ocr_vision <image>... | --list <file>\n".data(using: .utf8)!)
    exit(2)
}

var frameworkFailures = 0
for p in paths {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        emit(["path": p, "ok": false, "error": "cannot decode image"])
        continue
    }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["en-US", "th-TH"]
    do {
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    } catch {
        frameworkFailures += 1
        emit(["path": p, "ok": false, "error": "vision: \(error.localizedDescription)"])
        continue
    }
    let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    emit(["path": p, "ok": true, "lines": lines])
}
exit(frameworkFailures == paths.count ? 3 : 0)
