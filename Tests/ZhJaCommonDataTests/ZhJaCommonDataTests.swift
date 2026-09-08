import Foundation
import XCTest
import ZhJaCommonData
import ZhJaDictData

final class ZhJaCommonDataTests: XCTestCase {
    func testCommonProductFindsOnlyCommonResources() throws {
        XCTAssertEqual(ZhJaCommonData.bundleName, "zh-ja-dict_ZhJaCommonData.bundle")

        let entries = try XCTUnwrap(ZhJaCommonData.entriesURL())
        let manifest = try XCTUnwrap(ZhJaCommonData.manifestURL())
        XCTAssertEqual(entries.lastPathComponent, "entries.jsonl.deflate")
        XCTAssertEqual(manifest.lastPathComponent, "manifest.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: entries.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: manifest.path))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: entries.deletingLastPathComponent().appendingPathComponent("zh-ja").path))
    }

    func testNativeProductStillFindsNativeResources() throws {
        XCTAssertNotNil(ZhJaDictData.entriesURL())
        XCTAssertNotNil(ZhJaDictData.manifestURL())
    }
}
