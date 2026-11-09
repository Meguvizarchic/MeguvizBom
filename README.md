<div align="center">

# MeguvizBom

**Meguviz 家族的版本对齐（BOM）**

一次导入 · 对齐 Android / UI / Ref / Drawable / Hook 与可选桥

<br>

[![License](https://img.shields.io/badge/license-Apache--2.0-00AEEC?style=flat-square&labelColor=2d3a55)](LICENSE)
[![Issues](https://img.shields.io/github/issues/Meguvizarchic/MeguvizBom?style=flat-square&labelColor=2d3a55)](https://github.com/Meguvizarchic/MeguvizBom/issues)
[![CI](https://github.com/Meguvizarchic/MeguvizBom/actions/workflows/verify.yml/badge.svg)](https://github.com/Meguvizarchic/MeguvizBom/actions/workflows/verify.yml)

[用途](#用途) · [使用](#使用) · [成员](#成员) · [不在 BOM 内](#不在-bom-内) · [状态](#状态) · [验证](#验证) · [许可证](#许可证)

</div>

---

## 用途

Meguviz 的 Android、UI、Ref、Drawable 和 Hook 制品按 1.2.0 批次对齐；Lumen 到 MeguvizAndroid 的桥使用独立的 1.6.2 版本。这个 BOM 把各制品的版本约束放在一个坐标里。

BOM 只约束版本，不引入任何依赖；不用到的模块不会被拉进来。

## 使用

Gradle（Kotlin DSL）：

```kotlin
dependencies {
    implementation(platform("io.github.jichuo1.meguviz:meguviz-bom:1.2.0"))

    implementation("io.github.jichuo1.meguviz:meguviz-ui-widgets")   // 不写版本号
    implementation("io.github.jichuo1.meguviz:meguviz-android-window")
    implementation("io.github.jichuo1.meguviz.hook:hook-core")
}
```

Maven：

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>io.github.jichuo1.meguviz</groupId>
      <artifactId>meguviz-bom</artifactId>
      <version>1.2.0</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

- 用 `platform(...)`，不要用 `enforcedPlatform(...)`：前者给出推荐版本，宿主仍可以升级；后者会把版本强制传递给依赖你的人。
- BOM 同时发布 POM（Maven 读它）和 Gradle 模块元数据 `.module`（Gradle 读它）；Gradle 侧是否真的把版本套用到没写版本号的依赖，由 `verifyBom` 里的真实解析验证。
- BOM 1.2.0 对 Meguviz 家族成员推荐 1.2.0，对 Lumen 侧桥推荐 1.6.2；已发布的旧版本不会被修改。

## 成员

成员清单在 [`members.txt`](members.txt)，构建与校验工具读的是同一份文件。清单包含尚未发布的候选坐标，不表示它们已经可从 Central 下载。

| 来源仓库 | 制品与版本 |
| --- | --- |
| [MeguvizAndroid](https://github.com/Meguvizarchic/MeguvizAndroid) | `meguviz-android-runtime`、`-window`、`-lifecycle`、`-resources-loader` |
| [MeguvizUI](https://github.com/Meguvizarchic/MeguvizUI) | `meguviz-ui-core`、`-widgets`、`-plan`、`-text`、`-recycler`、`-layouts`、`-prewarm`、`-frame-shared`、`-codegen-api`、`-codegen`、`-ref-bridge`、`-android-bridge`、`-lumen-bridge` |
| [MeguvizRef](https://github.com/Meguvizarchic/MeguvizRef) | `meguviz-ref-core`、`-android`、`-diagnostics` |
| [MeguvizDrawable](https://github.com/Meguvizarchic/MeguvizDrawable) | `meguviz-drawable-core`、`-android`、`-compose`、`-meguviz-android`、`-meguviz-ui`、`-lumen` |
| [MeguvizHook](https://github.com/Meguvizarchic/MeguvizHook) | `io.github.jichuo1.meguviz.hook` 下的 `hook-api`、`hook-core`、`hook-dsl`、`hook-testing`、`hook-ref-bridge`、`backend-libxposed-101`、`backend-libxposed-102`，计划版本 1.2.0 |
| [LumenCoacervationEngine](https://github.com/Meguvizarchic/LumenCoacervationEngine) | 预留 `io.github.jichuo1:lumen-bridge-meguviz-android:1.6.2`；目前尚未发布 |

除表中单独注明的 Hook 和 Lumen 桥外，groupId 为 `io.github.jichuo1.meguviz`，版本为 1.2.0。Lumen 桥源码默认 group 与预留的 Central group 不同，发布桥时须显式选用并核对上述坐标。

## 不在 BOM 内

- **Lumen 核心模块**：`lumen-engine` 等模块独立定版；此 BOM 只列出 Lumen 到 MeguvizAndroid 的桥，不强制对齐整个 Lumen 发行版。

## 状态

`1.2.0` **尚未发布到 Maven Central**。BOM 只在所有成员都以清单指定的版本上了 Central 之后才发布。可以随时查看进度：

```sh
python3 tools/bom_tools.py central-status
```

输出每个成员的指定版本是否已在 Central；全部都有时加 `--require-all` 返回 0。独立版本不会被 `--version` 覆盖。

## 验证

```sh
./gradlew verifyBom
```

不需要网络和 Android SDK，包含三项检查：

1. `tools/test_bom_tools.py`：校验工具自己的单元测试，覆盖多出/缺少成员、版本不一致、缺 `platform` 类别、带真实依赖、缺 Maven Central 必填字段、校验和不匹配、上传包被改动、版本已在 Central 等失败情形。
2. `tools/bom_tools.py check`：生成的 POM 与 Gradle 模块元数据必须与 `members.txt` 的 group、artifact 和版本逐项一致。
3. `:alignment:verifyAlignment`：用占位 POM 代替成员，让 Gradle 真实解析“没写版本号”的跨 group 依赖，必须全部落在各自指定版本上；去掉 BOM 的对照组必须全部解析失败。

这些只证明版本对齐元数据正确，不证明各成员制品本身的内容或行为。

## 发布

流程、签名与上传步骤见 [docs/RELEASE.md](docs/RELEASE.md)。

## 许可证

[Apache License 2.0](LICENSE)。
