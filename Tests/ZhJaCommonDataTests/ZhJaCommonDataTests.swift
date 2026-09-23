import Foundation
import XCTest
import ZhJaCommonData
import ZhJaDictData

final class ZhJaCommonDataTests: XCTestCase {
    func testCommonProductFindsOnlyCommonResources() throws {
        XCTAssertEqual(ZhJaCommonData.bundleName, "zh-ja-dict_ZhJaCommonData.bundle")

        let database = try XCTUnwrap(ZhJaCommonData.databaseURL())
        let manifest = try XCTUnwrap(ZhJaCommonData.databaseManifestURL())
        XCTAssertEqual(database.lastPathComponent, "dictionary.sqlite3")
        XCTAssertEqual(manifest.lastPathComponent, "dictionary-db-manifest.json")
        XCTAssertTrue(FileManager.default.fileExists(atPath: database.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: manifest.path))
        let resourceDirectory = database.deletingLastPathComponent()
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: resourceDirectory.appendingPathComponent("entries.jsonl.deflate").path))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: resourceDirectory.appendingPathComponent("manifest.json").path))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: resourceDirectory.appendingPathComponent("zh-ja").path))
    }

    func testNativeProductStillFindsNativeResources() throws {
        XCTAssertNotNil(ZhJaDictData.entriesURL())
        XCTAssertNotNil(ZhJaDictData.manifestURL())
    }
}
