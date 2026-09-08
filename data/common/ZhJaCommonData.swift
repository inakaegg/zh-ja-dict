import Foundation

/// 共通辞書形式v1で同梱した中日データの在り処。
public enum ZhJaCommonData {
    /// このtargetのresource bundle名。
    public static let bundleName = "zh-ja-dict_ZhJaCommonData.bundle"

    /// 1行1 entryのJSON Linesをraw DEFLATEで圧縮した共通辞書本体。
    public static func entriesURL(in bundle: Bundle? = nil) -> URL? {
        (bundle ?? .module).url(forResource: "entries.jsonl", withExtension: "deflate")
    }

    /// 共通形式の版、件数、hash、native生成物の識別情報を持つmanifest。
    public static func manifestURL(in bundle: Bundle? = nil) -> URL? {
        (bundle ?? .module).url(forResource: "manifest", withExtension: "json")
    }
}
