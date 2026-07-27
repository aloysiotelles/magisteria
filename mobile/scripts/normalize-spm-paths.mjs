import { existsSync, readFileSync, writeFileSync } from 'node:fs';

const packageFile = 'ios/App/CapApp-SPM/Package.swift';
if (!existsSync(packageFile)) process.exit(0);

const manifest = JSON.parse(readFileSync('package.json', 'utf8'));
const capacitorVersion = String(manifest.devDependencies['@capacitor/ios']).replace(/^[^0-9]*/, '');
const plugins = [
  ['AparajitaCapacitorSecureStorage', '@aparajita/capacitor-secure-storage'],
  ['CapacitorApp', '@capacitor/app'],
  ['CapacitorBrowser', '@capacitor/browser'],
  ['CapacitorFileTransfer', '@capacitor/file-transfer'],
  ['CapacitorFilesystem', '@capacitor/filesystem'],
  ['CapacitorKeyboard', '@capacitor/keyboard'],
  ['CapacitorNetwork', '@capacitor/network'],
  ['CapacitorShare', '@capacitor/share'],
  ['CapacitorSplashScreen', '@capacitor/splash-screen'],
];
const packageLines = plugins
  .map(([name, path]) => `        .package(name: "${name}", path: "../../../node_modules/${path}")`)
  .join(',\n');
const productLines = plugins
  .map(([name]) => `                .product(name: "${name}", package: "${name}")`)
  .join(',\n');

const source = `// swift-tools-version: 5.9
import PackageDescription

// Regenerated after Capacitor sync to keep pnpm paths portable across operating systems.
let package = Package(
    name: "CapApp-SPM",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "CapApp-SPM", targets: ["CapApp-SPM"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "${capacitorVersion}"),
${packageLines}
    ],
    targets: [
        .target(
            name: "CapApp-SPM",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
${productLines}
            ]
        )
    ]
)
`;

writeFileSync(packageFile, source, 'utf8');
