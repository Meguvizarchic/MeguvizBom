import org.gradle.api.artifacts.component.ModuleComponentSelector
import org.gradle.api.artifacts.result.UnresolvedDependencyResult

plugins { base }

val bomGroup = "io.github.jichuo1.meguviz"
val bomVersion = rootProject.version.toString()

@Suppress("UNCHECKED_CAST")
val members = rootProject.extra["members"] as List<String>

@Suppress("UNCHECKED_CAST")
val stagingDir = rootProject.extra["stagingDir"] as Provider<Directory>
val stubDir = layout.buildDirectory.dir("stubs")

// Stub POMs (packaging pom, no files) stand in for the members; the staged BOM supplies their versions.
repositories {
    maven { name = "BomStaging"; url = stagingDir.get().asFile.toURI() }
    maven { name = "MemberStubs"; url = stubDir.get().asFile.toURI() }
}

fun resolvableUsingApi(name: String) = configurations.create(name) {
    isCanBeConsumed = false
    isCanBeResolved = true
    attributes { attribute(Usage.USAGE_ATTRIBUTE, objects.named(Usage::class.java, Usage.JAVA_API)) }
}

val aligned = resolvableUsingApi("bomAligned")
val control = resolvableUsingApi("bomControl")
dependencies {
    add(aligned.name, platform("$bomGroup:meguviz-bom:$bomVersion"))
    members.forEach {
        add(aligned.name, "$bomGroup:$it") // deliberately no version
        add(control.name, "$bomGroup:$it") // the same without the BOM: must not resolve
    }
}

val writeStubs = tasks.register("writeStubs") {
    val out = stubDir
    val artifacts = members
    outputs.dir(out)
    doLast {
        val root = out.get().asFile
        root.deleteRecursively()
        artifacts.forEach { artifact ->
            val directory = File(root, bomGroup.replace('.', '/') + "/$artifact/$bomVersion").apply { mkdirs() }
            File(directory, "$artifact-$bomVersion.pom").writeText(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
                    "<project xmlns=\"http://maven.apache.org/POM/4.0.0\"><modelVersion>4.0.0</modelVersion>" +
                    "<groupId>$bomGroup</groupId><artifactId>$artifact</artifactId><version>$bomVersion</version>" +
                    "<packaging>pom</packaging></project>\n"
            )
        }
    }
}

tasks.register("verifyAlignment") {
    group = "verification"
    description = "Resolves every member without a version through the staged BOM."
    dependsOn(":publishBomPublicationToStagingRepository", writeStubs)
    doLast {
        val graph = aligned.incoming.resolutionResult
        val unresolved = graph.allDependencies.filterIsInstance<UnresolvedDependencyResult>()
        check(unresolved.isEmpty()) { "unresolved with the BOM: " + unresolved.map { it.requested.displayName } }
        val versions = graph.allComponents.mapNotNull { it.moduleVersion }
            .filter { it.group == bomGroup }.associate { it.name to it.version }
        check(versions["meguviz-bom"] == bomVersion) { "the BOM itself did not resolve as $bomVersion: ${versions["meguviz-bom"]}" }
        val wrong = members.filter { versions[it] != bomVersion }
        check(wrong.isEmpty()) { "the BOM did not align to $bomVersion: $wrong" }

        val withoutBom = control.incoming.resolutionResult.allDependencies
            .filterIsInstance<UnresolvedDependencyResult>().map { (it.requested as ModuleComponentSelector).module }.toSet()
        check(withoutBom == members.toSet()) {
            "without the BOM these members still resolved, so the check proves nothing: ${members.toSet() - withoutBom}"
        }
        println("BOM $bomVersion OK: ${members.size} members aligned, ${withoutBom.size} unresolved without it")
    }
}
