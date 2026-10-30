import next from "eslint-config-next";

const config = [
  ...next,
  {
    rules: {
      // Syncing local UI state from props/URL/browser APIs inside effects is intentional here
      // (hydration-safe mounted flags, query-param prefills). Keep the rule as a warning.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  { ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**"] },
];

export default config;
