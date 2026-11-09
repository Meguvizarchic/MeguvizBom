# 发布

BOM 发布到 Maven Central，坐标 `io.github.jichuo1.meguviz:meguviz-bom:<版本>`。已发布的版本不可替换、不可撤销（Sonatype 的政策），所以先核对，后上传。

## 什么时候发

只在 [`members.txt`](../members.txt) 里的每个制品都以 BOM 版本上了 Central 之后发：

```sh
python3 tools/bom_tools.py central-status --require-all
```

返回 0 才继续。成员清单变化（加入新桥、移除模块）意味着一个新的 BOM 版本，不能回改已发布的版本。

## 版本号

`gradle.properties` 里的 `meguviz.version` 是整个批次的版本号，与各库的发布版本一致。BOM 自己不单独定版：批次是 1.2.0，BOM 就是 1.2.0。

## 步骤

1. 确认工作区干净、在 `main` 上，`./gradlew verifyBom` 通过。
2. 本机有 `gpg` 和用于 Central 的签名密钥时生成签名的上传包：

   ```sh
   ./gradlew -Pmeguviz.sign=true centralBundle
   ```

   签名口令由 gpg-agent 询问，不进入构建参数。包在 `build/central/meguviz-bom-<版本>-central-bundle.zip`，目录布局是 Maven 仓库布局，POM 与 `.module` 各带 `.asc` 和四种校验和；`maven-metadata.xml` 有意不放，由 Portal 生成。
3. 上传前再校验一遍，包括签名与“该版本还不在 Central 上”：

   ```sh
   python3 tools/bom_tools.py verify-bundle build/central/meguviz-bom-<版本>-central-bundle.zip --check-unpublished
   ```

   它不检查命名空间是否已在 Portal 上验证，也不检查公钥是否在 keyserver 上。
4. 在 [Central Portal](https://central.sonatype.com) 的 Publish 页上传该 zip，先选 User Managed 部署，校验通过后再手动 Publish。
5. 发布后：
   - 打与版本同名的 tag（`<版本>`，不加 `v`）并创建 GitHub Release；
   - 在 README 顶部加 Maven Central 徽章，并把“状态”一节改成已发布；
   - 在各库文档里把“尚未发布”的 BOM 说法改成已发布。

## 为什么没有 Javadoc 和 sources jar

BOM 是 `pom` 打包，没有 jar：Central 对这类制品只要求 POM（以及签名与校验和）。
