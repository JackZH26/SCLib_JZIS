// Version 2: region-scoped recognition on the original, uncropped page.
// V1 remains immutable for replay. No scientific interpretation or custom words.
import Foundation
import Vision
import ImageIO
import CryptoKit

func box(_ rect: CGRect) -> [Double] {
    // Vision recognition boxes are relative to the requested ROI. Persist
    // full-page coordinates; the unchanged full-page PNG remains the asset.
    let width = region[2] - region[0], height = region[3] - region[1]
    return [region[0] + Double(rect.minX) * width, region[1] + Double(1 - rect.maxY) * height,
            region[0] + Double(rect.maxX) * width, region[1] + Double(1 - rect.minY) * height]
}
guard CommandLine.arguments.count == 3 else { fatalError("PNG path and normalized top-left region JSON required") }
let regionData = Data(CommandLine.arguments[2].utf8)
let region = try JSONDecoder().decode([Double].self, from: regionData)
guard region.count == 4, region.allSatisfy({ $0.isFinite }),
      0 <= region[0], region[0] < region[2], region[2] <= 1,
      0 <= region[1], region[1] < region[3], region[3] <= 1 else { fatalError("bounded region required") }
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
request.minimumTextHeight = 0.001
request.regionOfInterest = CGRect(x: region[0], y: 1 - region[3], width: region[2] - region[0], height: region[3] - region[1])
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
let result: [String: Any] = ["schema": "materials-vision-text/2", "region_of_interest": region, "minimum_text_height": request.minimumTextHeight, "image_sha256": SHA256.hash(data: raw).map { String(format: "%02x", $0) }.joined(),
    "image_bytes": raw.count, "width": picture.width, "height": picture.height,
    "recognizer": "Apple Vision VNRecognizeTextRequest", "revision": request.revision, "recognition_level": "accurate",
    "language_correction": false, "recognition_languages": ["en-US"], "coordinate_system": "normalized_top_left_xyxy",
    "recognizer_coordinate_system": "normalized_roi_lower_left", "coordinates_transformed_to_full_page": true,
    "coordinate_precision": "approximate_word_boxes", "macos": ProcessInfo.processInfo.operatingSystemVersionString,
    "elapsed_seconds": Date().timeIntervalSince(started), "observations": observations, "scientific_acceptance": false]
let output = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
FileHandle.standardOutput.write(output)
