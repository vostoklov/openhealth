import XCTest
@testable import OpenHealth

final class ModelTests: XCTestCase {

    func testConfidenceBucketing() {
        XCTAssertEqual(Confidence(numeric: 0.9), .c5)
        XCTAssertEqual(Confidence(numeric: 0.7), .c4)
        XCTAssertEqual(Confidence(numeric: 0.45), .c3)
        XCTAssertEqual(Confidence(numeric: 0.3), .c2)
        XCTAssertEqual(Confidence(numeric: 0.1), .c1)
    }

    func testLowConfidenceFramesAsQuestion() {
        XCTAssertTrue(Confidence.c2.framesAsQuestion)
        XCTAssertTrue(Confidence.c3.framesAsQuestion)
        XCTAssertFalse(Confidence.c4.framesAsQuestion)
        XCTAssertFalse(Confidence.c5.framesAsQuestion)
    }

    func testMarkerFlagLabels() {
        XCTAssertEqual(MarkerFlag.normal.label, "in range")
        XCTAssertEqual(MarkerFlag.low.label, "low")
        XCTAssertEqual(MarkerFlag.high.label, "high")
    }

    func testSampleSnapshotDecodes() throws {
        let json = """
        {
          "greeting_name": "Test",
          "measurements": [{"metric":"sleep","title":"Sleep","value":"7 h","caption":null}],
          "panels": [{
            "id":"p1","date":"2024-06-01","title":"Panel",
            "markers":[{"marker_key":"vitamin_d","display_name":"Vitamin D","loinc":"1989-3",
              "value":18.0,"unit":"ng/mL","value_si":44.9,"si_unit":"nmol/L",
              "reference_low":30.0,"reference_high":null,"reference_source":"fallback",
              "flag":"low","note":null}]
          }],
          "trends": [],
          "insights": [{"id":"i1","title":"T","statement":"S","confidence":0.3,
            "open_questions":["q?"],"suggested_validation":null,"sources":[]}],
          "alerts": []
        }
        """.data(using: .utf8)!

        let snap = try JSONDecoder().decode(HealthSnapshot.self, from: json)
        XCTAssertEqual(snap.greetingName, "Test")
        XCTAssertEqual(snap.panels.first?.abnormal.count, 1)
        XCTAssertEqual(snap.panels.first?.markers.first?.flag, .low)
        XCTAssertEqual(snap.insights.first?.confidence, .c2)
        XCTAssertTrue(snap.insights.first!.confidence.framesAsQuestion)
    }
}
