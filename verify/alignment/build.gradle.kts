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
        val coordinate = it.substringBeforeLast(':')
        add(aligned.name, coordinate) // deliberately no version
        add(control.name, coordinate) // the same without the BOM: must not resolve
    }
}

val writeStubs = tasks.register("writeStubs") {
    val out = stubDir
    val artifacts = members
    outputs.dir(out)
    doLast {
        val root = out.get().asFile
        root.deleteRecursively()
        artifacts.forEach { member ->
            val (groupId, artifact, version) = member.split(':')
            val directory = File(root, groupId.replace('.', '/') + "/$artifact/$version").apply { mkdirs() }
            File(directory, "$artifact-$version.pom").writeText(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
                    "<project xmlns=\"http://maven.apache.org/POM/4.0.0\"><modelVersion>4.0.0</modelVersion>" +
                    "<groupId>$groupId</groupId><artifactId>$artifact</artifactId><version>$version</version>" +
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
            .associate { "${it.group}:${it.name}" to it.version }
        val bomCoordinate = "$bomGroup:meguviz-bom"
        check(versions[bomCoordinate] == bomVersion) { "the BOM itself did not resolve as $bomVersion: ${versions[bomCoordinate]}" }
        val wrong = members.filter { versions[it.substringBeforeLast(':')] != it.substringAfterLast(':') }
        check(wrong.isEmpty()) { "the BOM did not align its members: $wrong" }

        val withoutBom = control.incoming.resolutionResult.allDependencies
            .filterIsInstance<UnresolvedDependencyResult>().map {
                val requested = it.requested as ModuleComponentSelector
                "${requested.group}:${requested.module}"
            }.toSet()
        val memberCoordinates = members.map { it.substringBeforeLast(':') }.toSet()
        check(withoutBom == memberCoordinates) {
            "without the BOM these members still resolved, so the check proves nothing: ${memberCoordinates - withoutBom}"
        }
        println("BOM $bomVersion OK: ${members.size} members aligned, ${withoutBom.size} unresolved without it")
    }
}
