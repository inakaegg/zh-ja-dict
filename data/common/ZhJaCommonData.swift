import Foundation

/// 共通辞書形式v2の検索用SQLiteを同梱した中日データの在り処。
public enum ZhJaCommonData {
    /// このtargetのresource bundle名。
    public static let bundleName = "zh-ja-dict_ZhJaCommonData.bundle"

    /// 必要なentryだけを検索する共通辞書SQLite。
    public static func databaseURL(in bundle: Bundle? = nil) -> URL? {
        (bundle ?? .module).url(forResource: "dictionary", withExtension: "sqlite3")
    }

    /// SQLiteの版、件数、hash、監査用JSONLの識別情報を持つmanifest。
    public static func databaseManifestURL(in bundle: Bundle? = nil) -> URL? {
        (bundle ?? .module).url(
            forResource: "dictionary-db-manifest", withExtension: "json")
    }
}
