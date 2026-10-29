// ESLint 9 flat config (Next 16 removed `next lint`; run `eslint .`).
import nextVitals from "eslint-config-next/core-web-vitals";

const config = [
  // New with the React 19 hooks plugin: 7 components set state in an effect
  // (data loading, reading localStorage), which works today. Warn, not error,
  // so the framework upgrade stays behaviour-neutral. The override has to sit
  // in the config object that defines the react-hooks plugin.
  // ponytail: rewrite those effects (derived state / event handlers), then set
  // this back to "error".
  ...nextVitals.map((entry) =>
    entry.plugins?.["react-hooks"]
      ? { ...entry, rules: { ...entry.rules, "react-hooks/set-state-in-effect": "warn" } }
      : entry,
  ),
  { ignores: [".next/**", "out/**", "coverage/**", "node_modules/**", "next-env.d.ts"] },
];

export default config;
