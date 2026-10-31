// Local optical text and word-location capture. No scientific interpretation.
import Foundation
import Vision
import ImageIO
import CryptoKit

func box(_ rect: CGRect) -> [Double] {
    return [Double(rect.minX), Double(1 - rect.maxY), Double(rect.maxX), Double(1 - rect.minY)]
}
guard CommandLine.arguments.count == 2 else { fatalError("one PNG path required") }
let path = CommandLine.arguments[1]
let raw = try Data(contentsOf: URL(fileURLWithPath: path))
guard raw.count <= 12_000_000, let input = CGImageSourceCreateWithData(raw as CFData, nil),
      let picture = CGImageSourceCreateImageAtIndex(input, 0, nil),
      picture.width * picture.height <= 8_000_000 else { fatalError("bounded image required") }
guard VNRecognizeTextRequest.supportedRevisions.contains(3) else { fatalError("Vision revision 3 required") }
let request = VNRecognizeTextRequest()
request.revision = 3
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
request.recognitionLanguages = ["en-US"]
request.automaticallyDetectsLanguage = false
let started = Date()
try VNImageRequestHandler(cgImage: picture, orientation: .up, options: [:]).perform([request])
let tokenPattern = try NSRegularExpression(pattern: "\\S+")
let observations = (request.results ?? []).enumerated().compactMap { number, observation -> [String: Any]? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let text = candidate.string
    var words: [[String: Any]] = []
    for match in tokenPattern.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
        guard let span = Range(match.range, in: text), let region = try? candidate.boundingBox(for: span) else { continue }
        words.append(["text": String(text[span]), "start_char": text.unicodeScalars.distance(from: text.unicodeScalars.startIndex, to: span.lowerBound),
            "end_char": text.unicodeScalars.distance(from: text.unicodeScalars.startIndex, to: span.upperBound), "box": box(region.boundingBox)])
    }
    return ["id": "line:\(number)", "text": text, "confidence": Double(candidate.confidence), "box": box(observation.boundingBox), "words": words]
}
let result: [String: Any] = ["schema": "materials-vision-text/1", "image_sha256": SHA256.hash(data: raw).map { String(format: "%02x", $0) }.joined(),
    "image_bytes": raw.count, "width": picture.width, "height": picture.height,
    "recognizer": "Apple Vision VNRecognizeTextRequest", "revision": request.revision, "recognition_level": "accurate",
    "language_correction": false, "recognition_languages": ["en-US"], "coordinate_system": "normalized_top_left_xyxy",
    "coordinate_precision": "approximate_word_boxes", "macos": ProcessInfo.processInfo.operatingSystemVersionString,
    "elapsed_seconds": Date().timeIntervalSince(started), "observations": observations, "scientific_acceptance": false]
let output = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
FileHandle.standardOutput.write(output)
