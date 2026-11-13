// macOS Vision face detection for the YT-News V4 face-box tool (local only, no network).
//
//   swift face_vision.swift <image> [<image> ...]
//
// Always run through the `swift` interpreter (face_box.py does). Never build or cache an executable of this file.
// Prints one JSON object per input image, in input order:
//   {"path":"...","ok":true,"faces":[{"x":0.41,"y":0.16,"w":0.13,"h":0.24}, ...]}   (top-left origin, normalised 0..1;
//                                                                                    an empty list = no face found)
//   {"path":"...","ok":false,"error":"..."}          (unreadable image / Vision error)
// Exit codes: 0 = ran (per-image errors are reported in the JSON), 2 = usage error,
// 3 = Vision framework unusable on this machine (it failed on every image).
import Foundation
import Vision
import ImageIO

func emit(_ obj: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: obj, options: [.withoutEscapingSlashes]),
       let s = String(data: data, encoding: .utf8) {
        print(s)
    }
}

let paths = Array(CommandLine.arguments.dropFirst())
if paths.isEmpty {
    FileHandle.standardError.write("usage: face_vision <image>...\n".data(using: .utf8)!)
    exit(2)
}

var frameworkFailures = 0
for p in paths {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        emit(["path": p, "ok": false, "error": "cannot decode image"])
        continue
    }
    let req = VNDetectFaceRectanglesRequest()
    do {
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    } catch {
        frameworkFailures += 1
        emit(["path": p, "ok": false, "error": "vision: \(error.localizedDescription)"])
        continue
    }
    // Vision boundingBox has a bottom-left origin; convert to top-left.
    let faces: [[String: Double]] = (req.results ?? []).map { f in
        let b = f.boundingBox
        return ["x": Double(b.minX), "y": Double(1 - b.maxY), "w": Double(b.width), "h": Double(b.height)]
    }
    emit(["path": p, "ok": true, "faces": faces])
}
exit(frameworkFailures == paths.count ? 3 : 0)
