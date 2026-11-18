// Offline operator tool: recognize public policy images, retaining source pixel positions.
// Build: swiftc -module-cache-path /tmp/policy-swift-cache scripts/ocr-policy-images.swift -o /tmp/policy-ocr
import Foundation
import Vision
import ImageIO
import CoreGraphics

for path in CommandLine.arguments.dropFirst() {
    do {
        let url = URL(fileURLWithPath: path)
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            throw NSError(domain: "policy-ocr", code: 1)
        }
        var lines: [[String: Any]] = []
        let tileHeight = 2400, step = 2200
        for top in stride(from: 0, to: image.height, by: step) {
            let height = min(tileHeight, image.height - top)
            guard let tile = image.cropping(to: CGRect(x: 0, y: top, width: image.width, height: height)) else { continue }
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["zh-Hans", "en-US"]
            request.usesLanguageCorrection = true
            request.minimumTextHeight = 0.002
            try VNImageRequestHandler(cgImage: tile).perform([request])
            for result in request.results ?? [] {
                guard let text = result.topCandidates(1).first else { continue }
                let box = result.boundingBox
                let y = Double(top) + (1 - box.maxY) * Double(height)
                let x = box.minX * Double(image.width)
                let h = box.height * Double(height)
                let center = y + h / 2
                if top > 0 && center < Double(top + 100) { continue }
                if top + height < image.height && center >= Double(top + 2300) { continue }
                if lines.contains(where: { ($0["text"] as? String) == text.string && abs(($0["y"] as! Double) - y) < max(h, 12) && abs(($0["x"] as! Double) - x) < 30 }) { continue }
                lines.append(["text": text.string, "confidence": text.confidence, "x": x, "y": y,
                              "width": box.width * Double(image.width), "height": h])
            }
            if top + height >= image.height { break }
        }
        lines.sort { ($0["y"] as! Double) < ($1["y"] as! Double) }
        let payload: [String: Any] = ["method": "apple-vision-accurate-zh-Hans", "width": image.width,
                                     "height": image.height, "lines": lines,
                                     "text": lines.map { $0["text"] as! String }.joined(separator: "\n")]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        try data.write(to: URL(fileURLWithPath: path + ".ocr.json"), options: .atomic)
        print("recognized \(url.lastPathComponent): \(lines.count) lines")
    } catch { fputs("recognition failed: \(URL(fileURLWithPath: path).lastPathComponent): \(error)\n", stderr) }
}
