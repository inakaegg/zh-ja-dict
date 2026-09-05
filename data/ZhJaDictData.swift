import Foundation

/// 同梱した対訳データの在り処。
///
/// `Bundle.module` はこのモジュールの中でしか使えないので、読み手へURLを渡す入口をここに置く。
///
/// ## bundleを渡す必要がある場合
///
/// **既定の `Bundle.module` は、`.app` の中では当てにできない。** SwiftPMが生成するアクセサは
/// 2か所しか探さない。`.app` 直下（実行ファイルを包む `.app` と同じ階層）と、ビルドした機械の
/// 絶対pathで焼き込まれた `.build` である。アプリが資源を `Contents/Resources/` へ収めると
/// 前者は当たらず、**ビルドした機械では `.build` に当たって動いてしまう**。配布先には `.build` が
/// 無いので、そこで初めて見つからなくなる。
///
/// そのためアプリ側は、`bundleName` を手掛かりに自分で解決したbundleを渡すこと。
public enum ZhJaDictData {
    /// この target の資源bundleの名前。
    ///
    /// SwiftPMはpackage名とtarget名からこの名前を作る。読み手が `.app` の中を探すために要る。
    public static let bundleName = "zh-ja-dict_ZhJaDictData.bundle"

    /// 中日の対訳データ（JSON Lines）。見つからなければ `nil`。
    ///
    /// 見つからないのは同梱物の組み立てが壊れている場合なので、読み手は
    /// 「辞書が引けない」ではなく「同梱物が欠けている」と分かる形で扱うこと。
    public static func glossesURL(in bundle: Bundle? = nil) -> URL? {
        (bundle ?? .module).url(forResource: "glosses", withExtension: "jsonl", subdirectory: "zh-ja")
    }

    /// 形式の版と行数を申告する `manifest.json`。見つからなければ `nil`。
    ///
    /// 読み手の版検査に渡す。渡さないと、古い形式のデータを黙って読んで級を落とすことがある。
    public static func manifestURL(in bundle: Bundle? = nil) -> URL? {
        (bundle ?? .module).url(forResource: "manifest", withExtension: "json")
    }
}
