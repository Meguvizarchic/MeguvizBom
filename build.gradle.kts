plugins {
    `java-platform`
    `maven-publish`
    signing
}

val bomGroup = "io.github.jichuo1.meguviz"
group = bomGroup
version = providers.gradleProperty("meguviz.version").get()

// The single source of the BOM's contents. tools/bom_tools.py reads the same file.
val members: List<String> = file("members.txt").readLines()
    .map { it.substringBefore('#').trim() }
    .filter { it.isNotEmpty() }
    .map { member ->
        val parts = member.split(':')
        check(parts.size in 1..3) { "invalid member: $member" }
        val groupId = if (parts.size == 1) bomGroup else parts[0]
        val artifactId = if (parts.size == 1) parts[0] else parts[1]
        val memberVersion = if (parts.size == 3) parts[2] else project.version.toString()
        check(Regex("[A-Za-z0-9_-]+(\\.[A-Za-z0-9_-]+)*").matches(groupId) &&
            Regex("[A-Za-z0-9_][A-Za-z0-9_.-]*").matches(artifactId) &&
            Regex("[0-9]+\\.[0-9]+\\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?").matches(memberVersion) &&
            !memberVersion.endsWith("-SNAPSHOT", ignoreCase = true)) { "invalid member: $member" }
        "$groupId:$artifactId:$memberVersion"
    }
check(members.isNotEmpty()) { "members.txt lists no artifacts" }
val memberCoordinates = members.map { it.substringBeforeLast(':') }
check(memberCoordinates.toSet().size == members.size) { "members.txt lists an artifact twice" }
check("$bomGroup:meguviz-bom" !in memberCoordinates) { "the BOM must not constrain itself" }

dependencies {
    constraints {
        members.forEach { api(it) }
    }
}

val stagingDir = layout.buildDirectory.dir("staging-maven")
val pythonExecutable = providers.gradleProperty("pythonExecutable").getOrElse("python3")

publishing {
    publications {
        create<MavenPublication>("bom") {
            artifactId = "meguviz-bom"
            // Gradle emits both the POM (dependencyManagement) and the Gradle module metadata with platform
            // variants. Both are needed: a POM alone does not make Gradle apply the versions to unversioned
            // dependencies.
            from(components["javaPlatform"])
            pom {
                name.set("Meguviz family BOM")
                description.set("Aligns the Meguviz family and its optional integration bridges.")
                url.set("https://github.com/Meguvizarchic/MeguvizBom")
                licenses {
                    license {
                        name.set("The Apache License, Version 2.0")
                        url.set("https://www.apache.org/licenses/LICENSE-2.0.txt")
                        distribution.set("repo")
                    }
                }
                developers { developer { id.set("jichuo1"); name.set("jichuo1"); url.set("https://github.com/jichuo1") } }
                scm {
                    url.set("https://github.com/Meguvizarchic/MeguvizBom")
                    connection.set("scm:git:https://github.com/Meguvizarchic/MeguvizBom.git")
                    developerConnection.set("scm:git:ssh://git@github.com/Meguvizarchic/MeguvizBom.git")
                }
            }
        }
    }
    repositories {
        maven {
            name = "Staging"
            url = stagingDir.get().asFile.toURI()
        }
    }
}

// Signing only when asked for (-Pmeguviz.sign=true): it needs the maintainer's gpg key.
val signRequested = providers.gradleProperty("meguviz.sign").orNull == "true"
signing {
    isRequired = signRequested
    useGpgCmd()
    sign(publishing.publications["bom"])
}
tasks.withType<Sign>().configureEach { onlyIf { signRequested } }

val cleanStaging = tasks.register<Delete>("cleanStaging") { delete(stagingDir) }
tasks.matching { it.name == "publishBomPublicationToStagingRepository" }.configureEach { dependsOn(cleanStaging) }

// ---- Verification -------------------------------------------------------------------------------------------

val bomToolTests = tasks.register<Exec>("bomToolTests") {
    group = "verification"
    description = "Runs the unit tests of tools/bom_tools.py."
    commandLine(pythonExecutable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_bom_tools.py")
}

val checkStagedBom = tasks.register<Exec>("checkStagedBom") {
    group = "verification"
    description = "Checks the generated POM and Gradle module metadata against members.txt."
    dependsOn("publishBomPublicationToStagingRepository")
    commandLine(pythonExecutable, "tools/bom_tools.py", "check", "--repo", stagingDir.get().asFile.path)
}

// Proof that Gradle really applies the BOM lives in the :alignment subproject (a project must not resolve its own
// module coordinates). It reads `members` and the staged repository from here.
extra["members"] = members
extra["stagingDir"] = stagingDir

tasks.register("verifyBom") {
    group = "verification"
    description = "Everything that can be verified offline: tool tests, staged files, Gradle alignment."
    dependsOn(bomToolTests, checkStagedBom, ":alignment:verifyAlignment")
}

// ---- Central bundle -----------------------------------------------------------------------------------------

tasks.register<Exec>("centralBundle") {
    group = "publishing"
    description = "Zips the signed BOM in Maven Central layout. Run: ./gradlew -Pmeguviz.sign=true centralBundle"
    dependsOn("verifyBom")
    doFirst {
        check(signRequested) { "centralBundle requires -Pmeguviz.sign=true" }
    }
    val bundle = layout.buildDirectory.file("central/meguviz-bom-${project.version}-central-bundle.zip")
    commandLine(pythonExecutable, "tools/bom_tools.py", "bundle", "--repo", stagingDir.get().asFile.path,
        "--out", bundle.get().asFile.path, "--require-signatures")
}
