// java-platform, maven-publish and signing are core Gradle plugins: nothing is resolved from the network
// to build the BOM itself.
pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}

rootProject.name = "meguviz-bom"
include(":alignment")
project(":alignment").projectDir = file("verify/alignment")
