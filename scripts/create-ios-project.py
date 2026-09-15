"""Reproducible Xcode project; no third-party project generator required."""
from pathlib import Path
import hashlib
root = Path(__file__).resolve().parents[1] / 'ios'
project = root / 'Touchline.xcodeproj'
project.mkdir(exist_ok=True)
def uid(name): return hashlib.sha1(name.encode()).hexdigest()[:24].upper()
objects = []
def obj(name, body):
    objects.append(f'{uid(name)} = {{ {body} }};')
    return uid(name)
files = ['Models.swift', 'Store.swift', 'TouchlineApp.swift', 'Views.swift']
for f in files:
    obj(f, f'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {f}; sourceTree = "<group>";')
    obj('build'+f, f'isa = PBXBuildFile; fileRef = {uid(f)};')
obj('testsfile', 'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = TouchlineTests.swift; sourceTree = "<group>";')
obj('testsbuild', f'isa = PBXBuildFile; fileRef = {uid("testsfile")};')
obj('assets', 'isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = Assets.xcassets; sourceTree = "<group>";')
obj('assetsbuild', f'isa = PBXBuildFile; fileRef = {uid("assets")};')
obj('app', 'isa = PBXFileReference; explicitFileType = wrapper.application; path = Touchline.app; sourceTree = BUILT_PRODUCTS_DIR;')
obj('testapp', 'isa = PBXFileReference; explicitFileType = wrapper.cfbundle; path = TouchlineTests.xctest; sourceTree = BUILT_PRODUCTS_DIR;')
obj('main', f'isa = PBXGroup; children = ({uid("sources")},{uid("testgroup")},{uid("products")}); sourceTree = "<group>";')
obj('sources', 'isa = PBXGroup; children = (' + ','.join(uid(f) for f in files) + f',{uid("assets")}); path = Touchline; sourceTree = "<group>";')
obj('testgroup', f'isa = PBXGroup; children = ({uid("testsfile")}); path = TouchlineTests; sourceTree = "<group>";')
obj('products', f'isa = PBXGroup; children = ({uid("app")},{uid("testapp")}); name = Products; sourceTree = "<group>";')
obj('compile', 'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (' + ','.join(uid('build'+f) for f in files) + '); runOnlyForDeploymentPostprocessing = 0;')
obj('testcompile', f'isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({uid("testsbuild")}); runOnlyForDeploymentPostprocessing = 0;')
obj('resources', f'isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({uid("assetsbuild")}); runOnlyForDeploymentPostprocessing = 0;')
obj('frameworks', 'isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;')
obj('dependency', f'isa = PBXTargetDependency; target = {uid("target")}; targetProxy = {uid("proxy")};')
obj('proxy', f'isa = PBXContainerItemProxy; containerPortal = {uid("project")}; proxyType = 1; remoteGlobalIDString = {uid("target")}; remoteInfo = Touchline;')
obj('target', f'isa = PBXNativeTarget; buildConfigurationList = {uid("targetconfigs")}; buildPhases = ({uid("compile")},{uid("frameworks")},{uid("resources")}); buildRules = (); dependencies = (); name = Touchline; productName = Touchline; productReference = {uid("app")}; productType = "com.apple.product-type.application";')
obj('testtarget', f'isa = PBXNativeTarget; buildConfigurationList = {uid("testconfigs")}; buildPhases = ({uid("testcompile")}); buildRules = (); dependencies = ({uid("dependency")}); name = TouchlineTests; productName = TouchlineTests; productReference = {uid("testapp")}; productType = "com.apple.product-type.bundle.unit-test";')
for scope in ['project', 'target', 'test']:
    for mode in ['Debug', 'Release']:
        settings = 'SWIFT_VERSION = 5.0; IPHONEOS_DEPLOYMENT_TARGET = 17.0; SDKROOT = iphoneos; CLANG_ENABLE_MODULES = YES;'
        if scope == 'target':
            settings += ' PRODUCT_BUNDLE_IDENTIFIER = com.hughnolan.touchline; PRODUCT_NAME = "$(TARGET_NAME)"; GENERATE_INFOPLIST_FILE = YES; INFOPLIST_KEY_UILaunchScreen_Generation = YES; INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES; INFOPLIST_KEY_UIUserInterfaceStyle = Dark; INFOPLIST_KEY_CFBundleDisplayName = Touchline; TARGETED_DEVICE_FAMILY = 1; CODE_SIGN_STYLE = Automatic; CURRENT_PROJECT_VERSION = 1; MARKETING_VERSION = 1.0; ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; SUPPORTED_PLATFORMS = "iphoneos iphonesimulator"; SUPPORTS_MACCATALYST = NO;'
        elif scope == 'test':
            settings += ' PRODUCT_BUNDLE_IDENTIFIER = com.hughnolan.touchline.tests; PRODUCT_NAME = "$(TARGET_NAME)"; GENERATE_INFOPLIST_FILE = YES; TARGETED_DEVICE_FAMILY = 1; CODE_SIGN_STYLE = Automatic; TEST_HOST = "$(BUILT_PRODUCTS_DIR)/Touchline.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/Touchline"; BUNDLE_LOADER = "$(TEST_HOST)";'
        if mode == 'Debug':
            settings += ' SWIFT_OPTIMIZATION_LEVEL = "-Onone"; SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG; ENABLE_TESTABILITY = YES;'
        obj(scope+mode, f'isa = XCBuildConfiguration; buildSettings = {{ {settings} }}; name = {mode};')
    obj(scope+'configs', f'isa = XCConfigurationList; buildConfigurations = ({uid(scope+"Debug")},{uid(scope+"Release")}); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
obj('project', f'isa = PBXProject; attributes = {{ LastUpgradeCheck = 2600; TargetAttributes = {{ {uid("target")} = {{ CreatedOnToolsVersion = 26.0; }}; {uid("testtarget")} = {{ CreatedOnToolsVersion = 26.0; TestTargetID = {uid("target")}; }}; }}; }}; buildConfigurationList = {uid("projectconfigs")}; compatibilityVersion = "Xcode 14.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en,Base); mainGroup = {uid("main")}; productRefGroup = {uid("products")}; projectDirPath = ""; projectRoot = ""; targets = ({uid("target")},{uid("testtarget")});')
(project/'project.pbxproj').write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 56; objects = {\n'+'\n'.join(objects)+f'\n}}; rootObject = {uid("project")}; }}\n')
scheme = project/'xcshareddata/xcschemes'
scheme.mkdir(parents=True, exist_ok=True)
def ref(target, name): return f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{uid(target)}" BuildableName="{name}" BlueprintName="{name.split(".")[0]}" ReferencedContainer="container:Touchline.xcodeproj"/>'
(scheme/'Touchline.xcscheme').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2600" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{ref('target','Touchline.app')}</BuildActionEntry></BuildActionEntries></BuildAction>
<TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"><Testables><TestableReference skipped="NO">{ref('testtarget','TouchlineTests.xctest')}</TestableReference></Testables></TestAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref('target','Touchline.app')}</BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref('target','Touchline.app')}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>''')
print(project)
