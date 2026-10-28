const nextJest = require("next/jest");

const createJestConfig = nextJest({
  dir: "./",
});

const customJestConfig = {
  testEnvironment: "jest-environment-jsdom",
  setupFilesAfterEnv: ["<rootDir>/setupTests.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
  // Count every source file, not only the ones a test imports, so untested
  // pages show up as 0%. Thresholds are a ratchet at the measured baseline:
  // raise them as tests land, never lower them without review (docs/TESTING.md).
  collectCoverageFrom: ["{app,components,lib,providers}/**/*.{ts,tsx}", "!**/*.d.ts"],
  coverageThreshold: {
    global: { statements: 13, branches: 13, functions: 18, lines: 14 },
  },
};

module.exports = createJestConfig(customJestConfig);
