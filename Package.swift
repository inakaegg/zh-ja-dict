// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "zh-ja-dict",
    // 読み手のアプリに合わせる。iOS 17は同世代。
    platforms: [
        .macOS(.v14),
        .iOS(.v17)
    ],
    products: [
        .library(
            name: "ZhJaDictData",
            targets: ["ZhJaDictData"]
        )
    ],
    targets: [
        // データを動かさずに済ませるため、targetのpathを data/ へ寄せる。
        // resources は target の path の外を指せないので、repo直下に data/ がある構成では
        // こうするか、target の根を repo直下にして大量に exclude するかのどちらかになる。
        //
        // 日中（ja-zh）は資源に含めない。最初の読み手が中日しか使わないため、
        // 同梱を増やす理由が無い。必要になった時に target を足す。
        .target(
            name: "ZhJaDictData",
            path: "data",
            exclude: ["ja-zh"],
            sources: ["ZhJaDictData.swift"],
            resources: [
                .copy("zh-ja"),
                .copy("manifest.json")
            ]
        )
    ]
)
